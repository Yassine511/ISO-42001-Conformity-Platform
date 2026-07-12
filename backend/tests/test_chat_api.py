"""HTTP-level tests for the M4 chat endpoints."""

import json

import pytest
from fastapi.testclient import TestClient
from qdrant_client.http.exceptions import ResponseHandlingException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.chat import service as chat_service
from app.db import Base, get_db
from app.main import app
from app.pipeline import llm as llm_service
from tests.test_chat_service import (
    QUOTE,
    DOC_TEXT,
    QUESTION,
    FakeLLM,
    _draft,
    _org_claim,
    _policy_citation,
)


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    tc = TestClient(app)
    tc.session_factory = TestSession
    yield tc
    app.dependency_overrides.clear()
    llm_service.set_provider(None)


@pytest.fixture()
def org_id(client):
    org_id = client.post("/api/organizations", json={"name": "Chat API"}).json()["id"]
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique_ia.txt", DOC_TEXT.encode(), "text/plain")},
    )
    assert r.status_code == 201
    assert client.post(f"/api/organizations/{org_id}/index").status_code == 200
    return org_id


def test_chat_happy_path_and_replay(client, org_id):
    llm_service.set_provider(
        FakeLLM([_draft(claims=[_org_claim()], citations=[_policy_citation()])])
    )
    r = client.post(
        f"/api/organizations/{org_id}/chat/messages", json={"question": QUESTION}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ANSWERED"
    assert body["evidence_scope"] == "policy"
    assert body["conversation_id"]
    assert body["citations"][0]["match_method"] == "exact"
    # answer evidence == audit provenance here (single fully-verified claim)
    assert body["answer_citations"] == body["citations"]
    assert body["claims"][0]["citations_verified"] is True
    assert body["searched"]  # shows-its-work payload
    assert body["suggested_clause"] is None

    # conversations listing
    convs = client.get(f"/api/organizations/{org_id}/chat/conversations").json()
    assert len(convs) == 1 and convs[0]["id"] == body["conversation_id"]

    # replay is byte-for-byte from persistence
    msgs = client.get(
        f"/api/organizations/{org_id}/chat/conversations/{body['conversation_id']}/messages"
    ).json()
    assert len(msgs) == 1
    assert msgs[0]["answer"] == body["answer"]
    assert msgs[0]["citations"] == body["citations"]


def test_api_separates_model_quote_from_source_quote(client, org_id):
    llm_service.set_provider(
        FakeLLM(
            [_draft(claims=[_org_claim()], citations=[_policy_citation(quote=QUOTE.upper())])]
        )
    )
    body = client.post(
        f"/api/organizations/{org_id}/chat/messages", json={"question": QUESTION}
    ).json()
    assert body["status"] == "ANSWERED"
    [c] = body["answer_citations"]
    assert c["match_method"] == "exact"
    assert c["quote"] == QUOTE.upper()
    assert c["source_quote"] == QUOTE
    assert c["quote"] != c["source_quote"]


def test_chat_abstention_payload(client, org_id):
    # scripted fabricated quote → all claims dropped → abstention with clause
    fake_quote = "Un registre des incidents est tenu à jour par le RSSI chaque trimestre."
    llm_service.set_provider(
        FakeLLM([_draft(claims=[_org_claim()], citations=[_policy_citation(quote=fake_quote)])])
    )
    body = client.post(
        f"/api/organizations/{org_id}/chat/messages", json={"question": QUESTION}
    ).json()
    assert body["status"] == "ABSTAINED"
    assert body["abstain_reason"] == "verification_failed"
    assert body["answer"].startswith("Aucune preuve vérifiable")
    assert body["suggested_clause"] is not None
    assert body["stripped_citations"]


def test_chat_provider_failure_is_200_abstained(client, org_id):
    llm_service.set_provider(FakeLLM([None]))
    r = client.post(
        f"/api/organizations/{org_id}/chat/messages", json={"question": QUESTION}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ABSTAINED"
    assert body["abstain_reason"] == "llm_error"
    # exchange entered the audit log despite the infrastructure failure
    msgs = client.get(
        f"/api/organizations/{org_id}/chat/conversations/{body['conversation_id']}/messages"
    ).json()
    assert len(msgs) == 1


def test_chat_404s_and_validation(client, org_id):
    r = client.post("/api/organizations/nope/chat/messages", json={"question": "Q?"})
    assert r.status_code == 404
    assert r.json()["detail"] == "Organisation introuvable."

    r = client.post(
        f"/api/organizations/{org_id}/chat/messages",
        json={"question": "Q?", "conversation_id": "nope"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Conversation introuvable."

    # conversation of ANOTHER org is invisible
    other = client.post("/api/organizations", json={"name": "Autre"}).json()["id"]
    llm_service.set_provider(FakeLLM([None]))
    conv_id = client.post(
        f"/api/organizations/{org_id}/chat/messages", json={"question": "Q?"}
    ).json()["conversation_id"]
    r = client.post(
        f"/api/organizations/{other}/chat/messages",
        json={"question": "Q?", "conversation_id": conv_id},
    )
    assert r.status_code == 404
    assert (
        client.get(
            f"/api/organizations/{other}/chat/conversations/{conv_id}/messages"
        ).status_code
        == 404
    )

    # question too long → 422
    r = client.post(
        f"/api/organizations/{org_id}/chat/messages", json={"question": "x" * 2001}
    )
    assert r.status_code == 422


def _seed_message(session_factory, org_id, *, claims, citations, retrieved_policy=None):
    """Insert a chat message row directly (bypassing the service), as the
    pre-ad46dbe code would have persisted it."""
    from app.models import ChatMessage, Conversation

    db = session_factory()
    conv = Conversation(organization_id=org_id, title="Legacy")
    db.add(conv)
    db.flush()
    msg = ChatMessage(
        conversation_id=conv.id,
        question="Question héritée ?",
        status="ANSWERED",
        abstain_reason=None,
        answer="Réponse héritée.",
        evidence_scope="policy",
        claims=claims,
        citations=citations,
        stripped_citations=[],
        retrieved_policy=retrieved_policy or [],
        retrieved_kb=[],
        attempts=[{"attempt_number": 1, "parsed_ok": True, "validation_errors": []}],
        draft_attempts=1,
        prompt_version="1",
        corpus_version="1.0.0",
    )
    db.add(msg)
    db.commit()
    conv_id = conv.id
    db.close()
    return conv_id


def test_replay_of_legacy_verified_key_rows(client, org_id):
    """Rows persisted before the citations_verified rename (audit round 13 P0)
    must replay: the serializer normalizes the legacy `verified` key and
    answer_citations is preserved — in claim-reference order (P2)."""
    conv_id = _seed_message(
        client.session_factory,
        org_id,
        claims=[
            {
                "text": "Affirmation héritée.",
                "kind": "organization",
                # references c1 then c2, while citations are DECLARED c2 first:
                # the response must follow reference order (c1, c2)
                "citation_ids": ["c1", "c2"],
                "verified": True,  # legacy key
                "failed_citation_ids": [],
            }
        ],
        citations=[
            {"id": "c2", "type": "kb", "requirement_id": "A.9.2",
             "requirement_fr": "Exigence.", "domain": "A.9"},
            # legacy shape: no source_quote key; offsets span the full quote
            {"id": "c1", "type": "policy", "quote": QUOTE.upper(), "chunk_id": "x",
             "document_id": "d", "filename": "f.txt", "page_number": 1,
             "match_start": 0, "match_end": len(QUOTE), "match_method": "exact",
             "match_score": 100.0},
        ],
        retrieved_policy=[
            {"result_id": "x", "source_type": "policy", "text": QUOTE,
             "rrf_score": 0.03, "vector_rank": 1, "bm25_rank": 1,
             "document_id": "d", "filename": "f.txt", "page_number": 1,
             "char_start": 0, "char_end": len(QUOTE),
             "requirement_id": None, "domain": None},
        ],
    )
    r = client.get(
        f"/api/organizations/{org_id}/chat/conversations/{conv_id}/messages"
    )
    assert r.status_code == 200
    [msg] = r.json()
    assert msg["claims"][0]["citations_verified"] is True
    assert "verified" not in msg["claims"][0]
    assert [c["id"] for c in msg["answer_citations"]] == ["c1", "c2"]  # reference order
    assert [c["id"] for c in msg["citations"]] == ["c2", "c1"]  # audit list untouched
    # source_quote backfilled from the persisted retrieval snapshot, validated
    # against the stored quote (normalized equality)
    legacy_policy = msg["answer_citations"][0]
    assert legacy_policy["quote"] == QUOTE.upper()
    assert legacy_policy["source_quote"] == QUOTE
    assert legacy_policy["source_quote_error"] is None


def test_replay_of_corrupted_legacy_offsets_fails_closed(client, org_id):
    """Out-of-bounds legacy offsets must yield source_quote=null + a French
    provenance error, never a truncated slice presented as authoritative."""
    conv_id = _seed_message(
        client.session_factory,
        org_id,
        claims=[
            {"text": "A.", "kind": "organization", "citation_ids": ["c1"],
             "verified": True, "failed_citation_ids": []}
        ],
        citations=[
            {"id": "c1", "type": "policy", "quote": QUOTE, "chunk_id": "x",
             "document_id": "d", "filename": "f.txt", "page_number": 1,
             "match_start": 5, "match_end": len(QUOTE) + 999,  # past chunk end
             "match_method": "exact", "match_score": 100.0},
        ],
        retrieved_policy=[
            {"result_id": "x", "source_type": "policy", "text": QUOTE,
             "rrf_score": 0.03, "vector_rank": 1, "bm25_rank": 1,
             "document_id": "d", "filename": "f.txt", "page_number": 1,
             "char_start": 0, "char_end": len(QUOTE),
             "requirement_id": None, "domain": None},
        ],
    )
    r = client.get(
        f"/api/organizations/{org_id}/chat/conversations/{conv_id}/messages"
    )
    assert r.status_code == 200
    [c] = r.json()[0]["answer_citations"]
    assert c["source_quote"] is None
    assert "offsets" in c["source_quote_error"]


def test_chat_qdrant_down_is_503(client, org_id, monkeypatch):
    def boom(*args, **kwargs):
        raise ResponseHandlingException("connexion refusée")

    monkeypatch.setattr(chat_service, "hybrid_search", boom)
    r = client.post(
        f"/api/organizations/{org_id}/chat/messages", json={"question": QUESTION}
    )
    assert r.status_code == 503
    assert "Index vectoriel indisponible" in r.json()["detail"]
    # nothing persisted
    assert client.get(f"/api/organizations/{org_id}/chat/conversations").json() == []


def test_kb_only_flag_reaches_service(client, org_id, monkeypatch):
    """The router forwards kb_only; the service then never searches the
    policy arm and the persisted replay shows an empty policy retrieval."""
    seen = {}
    real_ask = chat_service.ask

    def spy(db, org, question, conversation_id=None, **kw):
        seen.update(kw)
        return real_ask(db, org, question, conversation_id, **kw)

    monkeypatch.setattr("app.api.chat.service.ask", spy)
    llm_service.set_provider(
        FakeLLM([_draft(no_evidence=True), ])
    )
    r = client.post(
        f"/api/organizations/{org_id}/chat/messages",
        json={"question": QUESTION, "kb_only": True},
    )
    assert r.status_code == 200
    assert seen["kb_only"] is True
    body = r.json()
    # no policy passages were searched or displayed in the audit payload
    assert all(item["source_type"] != "policy" for item in body["searched"])

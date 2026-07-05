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

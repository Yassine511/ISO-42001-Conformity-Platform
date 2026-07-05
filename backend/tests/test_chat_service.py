"""Service-level tests for the M4 grounded chat (claim-bound trust rules).

Offline: FakeLLM (scripted, llm.set_provider) + FakeEmbedder + in-memory
Qdrant (autouse, conftest.py) + sqlite. KB comes from the real corpus files
(load_kb), so clause refs like A.9.2 resolve exactly as in production.
"""

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.chat import service
from app.chat.prompts import CHAT_PROMPT_VERSION
from app.db import Base
from app.models import ChatLlmCall, ChatMessage, Conversation, Document, DocumentPage, Organization
from app.pipeline import llm as llm_service
from app.pipeline.llm import (
    CALL_HTTP_ERROR,
    CALL_SUCCESS,
    LLMCall,
    LLMOutcome,
)
from app.services.parsing import PARSER_VERSION
from app.services.retrieval import hybrid_search, index_organization

KB_CLAUSE = "A.9.2"  # exists in the corpus KB

QUOTE = "Les collaborateurs doivent signaler tout incident dans un délai de 48 heures."
DOC_TEXT = (
    "Politique d'utilisation responsable des systèmes d'intelligence artificielle.\n\n"
    "Seuls les systèmes approuvés par le Comité IA peuvent être utilisés.\n\n"
    f"{QUOTE}\n\n"
    "Toute exception doit être documentée et validée par la direction."
)
QUESTION = "Comment les incidents liés aux systèmes d'intelligence artificielle sont-ils signalés ?"


class FakeLLM:
    """Scripted provider. Entries: raw content str, None (all providers
    failed, 500), or "RATE_LIMITED" sentinel (429-only trail)."""

    RATE = object()

    def __init__(self, scripts: list):
        self.scripts = list(scripts)
        self.requests: list[list[dict]] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def complete_json(self, messages, *, json_schema=None, schema_name="draft_finding"):
        self.requests.append(messages)
        content = self.scripts.pop(0)
        now = "2026-07-05T00:00:00+00:00"
        if content is None or content is FakeLLM.RATE:
            status_code = 429 if content is FakeLLM.RATE else 500
            call = LLMCall(
                provider="mistral",
                requested_model="fake-large",
                status=CALL_HTTP_ERROR,
                request_messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0,
                http_status=status_code,
                error="boom",
                started_at=now,
                finished_at=now,
            )
            return LLMOutcome(content=None, calls=[call], error="tous les fournisseurs ont échoué")
        call = LLMCall(
            provider="fake",
            requested_model="fake-model",
            status=CALL_SUCCESS,
            request_messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            reported_model="fake-model-v1",
            raw_response=content,
            started_at=now,
            finished_at=now,
        )
        return LLMOutcome(content=content, calls=[call])


def _draft(claims=None, citations=None, no_evidence=False, retrieval_notes=None) -> str:
    return json.dumps(
        {
            "claims": claims or [],
            "no_evidence": no_evidence,
            "citations": citations or [],
            "retrieval_notes": retrieval_notes,
        },
        ensure_ascii=False,
    )


def _policy_citation(cid="c1", quote=QUOTE):
    return {"id": cid, "type": "policy", "policy_quote": quote, "clause_ref": None}


def _kb_citation(cid="c2", clause=KB_CLAUSE):
    return {"id": cid, "type": "kb", "policy_quote": None, "clause_ref": clause}


def _org_claim(text="Les incidents sont signalés sous 48 heures.", ids=("c1",)):
    return {"text": text, "kind": "organization", "citation_ids": list(ids)}


def _std_claim(text="La norme exige un processus de signalement des incidents.", ids=("c2",)):
    return {"text": text, "kind": "standard", "citation_ids": list(ids)}


@pytest.fixture()
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    db = session_factory()
    org = Organization(name="Chat Test")
    db.add(org)
    db.commit()
    doc = Document(
        organization_id=org.id,
        filename="politique_ia.txt",
        content_type="text/plain",
        status="parsed",
        page_count=1,
        checksum="deadbeef",
        parser_version=PARSER_VERSION,
    )
    db.add(doc)
    db.commit()
    db.add(DocumentPage(document_id=doc.id, page_number=1, text=DOC_TEXT))
    db.commit()
    index_organization(db, org.id)
    org_id = org.id
    db.close()
    yield session_factory, org_id
    llm_service.set_provider(None)


def _ask(env, scripts, question=QUESTION, org_id=None, conversation_id=None, **kw):
    session_factory, default_org = env
    fake = FakeLLM(scripts)
    llm_service.set_provider(fake)
    db = session_factory()
    try:
        message = service.ask(
            db, org_id or default_org, question, conversation_id, **kw
        )
    finally:
        db.close()
    return session_factory, fake, message


def _retrieved_kb_ids(env, question=QUESTION, k_kb=4):
    """KB clause ids the service will retrieve (deterministic) — a valid KB
    citation must reference one of these."""
    session_factory, org_id = env
    db = session_factory()
    try:
        items = hybrid_search(db, org_id, question, k=k_kb, scope="kb")
    finally:
        db.close()
    return [i.requirement_id for i in items]


def _displayed_policy_ids(env, question=QUESTION, k_policy=8):
    """Retrieval is deterministic: precompute the result_ids the service will
    display, to script coverage-complete retrieval_notes."""
    session_factory, org_id = env
    db = session_factory()
    try:
        items = hybrid_search(db, org_id, question, k=k_policy, scope="policy")
    finally:
        db.close()
    return [i.result_id for i in items]


def _notes(ids):
    return [{"result_id": rid, "reason": "ne traite pas la question"} for rid in ids]


# ------------------------------------------------------------- answered paths


def test_verbatim_quote_answered_policy_scope(env):
    _, fake, m = _ask(
        env, [_draft(claims=[_org_claim()], citations=[_policy_citation()])]
    )
    assert m.status == "ANSWERED"
    assert m.evidence_scope == "policy"
    assert m.abstain_reason is None
    assert "48 heures" in m.answer
    assert fake.call_count == 1
    [citation] = m.citations
    assert citation["type"] == "policy"
    assert citation["match_method"] == "exact"
    assert citation["match_score"] == 100.0
    assert citation["match_start"] is not None and citation["match_end"] is not None
    assert citation["filename"] == "politique_ia.txt"
    assert m.stripped_citations == []


def test_kb_citation_hydrated_and_kb_only_caveat(env):
    clause = _retrieved_kb_ids(env)[0]
    _, _, m = _ask(
        env, [_draft(claims=[_std_claim()], citations=[_kb_citation(clause=clause)])]
    )
    assert m.status == "ANSWERED"
    assert m.evidence_scope == "kb_only"
    [citation] = m.citations
    assert citation["type"] == "kb"
    assert citation["requirement_id"] == clause
    # display text hydrated from the KB, never from model output
    assert citation["requirement_fr"]
    assert service.KB_ONLY_CAVEAT in m.answer


def test_kb_citation_must_be_retrieved(env):
    # a clause that EXISTS in the standard but was never retrieved for this
    # question is a hallucination, not evidence — stripped (audit round 12 §2)
    retrieved = set(_retrieved_kb_ids(env))
    unretrieved = next(c for c in ("4.1", "5.2", "A.2.2", KB_CLAUSE) if c not in retrieved)
    _, _, m = _ask(
        env,
        [_draft(claims=[_std_claim()], citations=[_kb_citation(clause=unretrieved)])],
    )
    assert m.status == "ABSTAINED"
    assert m.abstain_reason == "verification_failed"
    [stripped] = m.stripped_citations
    assert "récupérées" in stripped["error"]


def test_mixed_scopes_both_claims_no_caveat(env):
    clause = _retrieved_kb_ids(env)[0]
    _, _, m = _ask(
        env,
        [
            _draft(
                claims=[_org_claim(), _std_claim()],
                citations=[_policy_citation(), _kb_citation(clause=clause)],
            )
        ],
    )
    assert m.status == "ANSWERED"
    assert m.evidence_scope == "mixed"
    assert "48 heures" in m.answer
    assert "processus de signalement" in m.answer
    assert service.KB_ONLY_CAVEAT not in m.answer


def test_scope_derives_from_cited_types_not_claim_kinds(env):
    # a single STANDARD claim citing a verified policy quote AND a retrieved
    # KB clause: scope must be mixed, and the kb_only caveat (which would
    # falsely deny that a policy passage was cited) must not appear
    # (audit round 12 §3)
    clause = _retrieved_kb_ids(env)[0]
    std = {
        "text": "La norme exige un signalement, ce que la politique applique.",
        "kind": "standard",
        "citation_ids": ["c1", "c2"],
    }
    _, _, m = _ask(
        env,
        [_draft(claims=[std], citations=[_policy_citation(), _kb_citation(clause=clause)])],
    )
    assert m.status == "ANSWERED"
    assert m.evidence_scope == "mixed"
    assert service.KB_ONLY_CAVEAT not in m.answer


# ------------------------------------------------- claim-binding trust rules


def test_fabricated_quote_sole_support_abstains(env):
    fake_quote = "Un registre des incidents est tenu à jour par le RSSI chaque trimestre."
    _, _, m = _ask(
        env,
        [_draft(claims=[_org_claim(ids=("c1",))], citations=[_policy_citation(quote=fake_quote)])],
    )
    assert m.status == "ABSTAINED"
    assert m.abstain_reason == "verification_failed"
    assert m.evidence_scope is None
    assert m.answer.startswith("Aucune preuve vérifiable")
    [stripped] = m.stripped_citations
    assert "introuvable" in stripped["error"]
    assert m.citations == []


def test_claim_binding_dropped_claim_text_absent(env):
    fake_quote = "Un registre des incidents est tenu à jour par le RSSI chaque trimestre."
    dropped_text = "Un registre trimestriel des incidents est tenu."
    kept_text = "Les incidents sont signalés sous 48 heures."
    _, _, m = _ask(
        env,
        [
            _draft(
                claims=[
                    _org_claim(text=dropped_text, ids=("c9",)),
                    _org_claim(text=kept_text, ids=("c1",)),
                ],
                citations=[
                    _policy_citation(cid="c9", quote=fake_quote),
                    _policy_citation(cid="c1"),
                ],
            )
        ],
    )
    assert m.status == "ANSWERED"
    assert kept_text in m.answer
    assert dropped_text not in m.answer
    dropped = [c for c in m.claims if not c["citations_verified"]]
    assert dropped and dropped[0]["failed_citation_ids"] == ["c9"]
    # answer/audit separation (audit round 12 §5): only citations referenced
    # by surviving claims back the final answer
    assert service.answer_citation_ids(m.claims) == ["c1"]


def test_all_citations_must_verify_partial_support_dropped(env):
    # one claim citing a VERIFIED policy quote AND a fabricated KB clause:
    # the whole claim is dropped — partial support never survives
    claim = {
        "text": "Le signalement sous 48 heures répond à l'exigence A.99.9.",
        "kind": "organization",
        "citation_ids": ["c1", "c2"],
    }
    _, _, m = _ask(
        env,
        [
            _draft(
                claims=[claim],
                citations=[_policy_citation(), _kb_citation(clause="A.99.9")],
            )
        ],
    )
    assert m.status == "ABSTAINED"
    assert m.abstain_reason == "verification_failed"
    assert claim["text"] not in m.answer
    [stripped] = m.stripped_citations
    assert "A.99.9" in stripped["error"]
    # the valid quote is still recorded as a verified citation (provenance)
    assert [c["id"] for c in m.citations] == ["c1"]


def test_kind_coherence_is_parse_error_then_repair(env):
    # organization claim citing only a KB id → schema-level parse error → repair
    bad = _draft(
        claims=[{"text": "Nous couvrons l'exigence.", "kind": "organization", "citation_ids": ["c2"]}],
        citations=[_kb_citation()],
    )
    good = _draft(claims=[_org_claim()], citations=[_policy_citation()])
    _, fake, m = _ask(env, [bad, good])
    assert fake.call_count == 2
    assert m.status == "ANSWERED"
    assert m.draft_attempts == 2
    assert m.attempts[0]["parsed_ok"] is False
    assert any("organization" in e for e in m.attempts[0]["validation_errors"])


def test_fuzzy_quote_stripped_with_provenance(env):
    fuzzy = QUOTE.replace("dans", "dnas")  # adjacent transposition → fuzzy path
    _, _, m = _ask(
        env, [_draft(claims=[_org_claim()], citations=[_policy_citation(quote=fuzzy)])]
    )
    assert m.status == "ABSTAINED"
    assert m.abstain_reason == "verification_failed"
    [stripped] = m.stripped_citations
    assert "approximative" in stripped["error"]
    assert stripped["match"]["method"] == "fuzzy"
    assert stripped["match"]["score"] >= 92.0
    assert stripped["match"]["match_start"] is not None


# ------------------------------------------------------------ abstention paths


def test_no_evidence_abstains_with_suggested_clause(env):
    ids = _displayed_policy_ids(env)
    _, _, m = _ask(env, [_draft(no_evidence=True, retrieval_notes=_notes(ids))])
    assert m.status == "ABSTAINED"
    assert m.abstain_reason == "model_abstained"
    assert m.answer.startswith("Aucune preuve vérifiable")
    assert "parmi les passages récupérés" in m.answer
    assert "à examiner" in m.answer  # clause suggested from retrieved KB
    assert m.retrieved_kb  # KB arm retrieved something to suggest
    assert len(m.retrieval_notes) == len(ids)


def test_retrieval_notes_coverage_enforced(env):
    ids = _displayed_policy_ids(env)
    # missing notes with no_evidence=true → parse error → repair → abstain
    missing = _draft(no_evidence=True, retrieval_notes=None)
    _, fake, m = _ask(env, [missing, missing])
    assert fake.call_count == 2
    assert m.status == "ABSTAINED"
    assert m.abstain_reason == "verification_failed"
    assert m.draft_attempts == 2
    assert all(not a["parsed_ok"] for a in m.attempts)
    assert any("retrieval_notes" in e for a in m.attempts for e in a["validation_errors"])

    # notes present with no_evidence=false → parse error, then valid → answered
    forbidden = _draft(
        claims=[_org_claim()], citations=[_policy_citation()], retrieval_notes=_notes(ids)
    )
    good = _draft(claims=[_org_claim()], citations=[_policy_citation()])
    _, fake2, m2 = _ask(env, [forbidden, good])
    assert fake2.call_count == 2
    assert m2.status == "ANSWERED"
    assert any("interdites" in e for e in m2.attempts[0]["validation_errors"])


def test_empty_notes_allowed_when_no_documents(env):
    session_factory, _ = env
    db = session_factory()
    org2 = Organization(name="Sans Documents")
    db.add(org2)
    db.commit()
    org2_id = org2.id
    db.close()
    _, _, m = _ask(env, [_draft(no_evidence=True)], org_id=org2_id)
    assert m.status == "ABSTAINED"
    assert m.abstain_reason == "model_abstained"
    assert m.retrieved_policy == []


def test_incoherent_no_evidence_with_claims_abstains(env):
    ids = _displayed_policy_ids(env)
    _, _, m = _ask(
        env,
        [
            _draft(
                claims=[_org_claim()],
                citations=[_policy_citation()],
                no_evidence=True,
                retrieval_notes=_notes(ids),
            )
        ],
    )
    assert m.status == "ABSTAINED"
    assert m.abstain_reason == "model_abstained"
    assert any("incohérence" in e for e in m.attempts[-1]["validation_errors"])


def test_malformed_json_twice_abstains(env):
    _, fake, m = _ask(env, ["pas du json", "toujours pas"])
    assert fake.call_count == 2
    assert m.status == "ABSTAINED"
    assert m.abstain_reason == "verification_failed"
    assert m.draft_attempts == 2
    assert [a["parsed_ok"] for a in m.attempts] == [False, False]
    # repair message carried the parse error back to the model
    repair = fake.requests[1][-1]["content"]
    assert "JSON invalide" in repair


def test_provider_failure_infrastructure_abstention(env):
    _, _, m = _ask(env, [None])
    assert m.status == "ABSTAINED"
    assert m.abstain_reason == "llm_error"
    assert m.answer == service.INFRA_ABSTENTION
    assert "Aucune preuve" not in m.answer  # never claims evidence absence
    assert m.final_model is None

    _, _, m2 = _ask(env, [FakeLLM.RATE])
    assert m2.abstain_reason == "rate_limited"


# --------------------------------------------------------------- persistence


def test_persistence_and_conversation_reuse(env):
    bad = "pas du json"
    good = _draft(claims=[_org_claim()], citations=[_policy_citation()])
    session_factory, fake, m = _ask(env, [bad, good])

    db = session_factory()
    row = db.get(ChatMessage, m.id)
    assert row.status == "ANSWERED"
    assert row.prompt_version == CHAT_PROMPT_VERSION
    assert row.corpus_version
    assert row.retrieved_policy and row.retrieved_kb
    assert row.raw_draft == good
    assert row.final_provider == "fake"
    assert row.final_model == "fake-model-v1"
    calls = db.scalars(
        select(ChatLlmCall).order_by(ChatLlmCall.call_number)
    ).all()
    assert [c.call_number for c in calls] == [1, 2]  # continues across the retry
    assert [c.draft_attempt_number for c in calls] == [1, 2]
    conv = db.get(Conversation, row.conversation_id)
    assert conv.title.startswith(QUESTION[:50])
    conv_id = conv.id
    db.close()

    # second message appended to the same conversation
    clause = _retrieved_kb_ids(env)[0]
    _, _, m2 = _ask(
        env,
        [_draft(claims=[_std_claim()], citations=[_kb_citation(clause=clause)])],
        conversation_id=conv_id,
    )
    assert m2.conversation_id == conv_id
    db = session_factory()
    msgs = db.scalars(
        select(ChatMessage).where(ChatMessage.conversation_id == conv_id)
    ).all()
    assert len(msgs) == 2
    db.close()


def test_unknown_conversation_rejected(env):
    with pytest.raises(service.ConversationNotFoundError):
        _ask(env, [], conversation_id="nope")

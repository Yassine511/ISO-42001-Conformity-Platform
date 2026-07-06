"""HTTP-level tests for the M5 HITL review endpoints.

Findings are produced by the real pipeline (FakeLLM) through the API-side
session factory, then reviewed over HTTP. The core invariant under test: the
AI draft is write-once — review touches only review_* columns and the
immutable finding_reviews history.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import assessments as assessments_api
from app.db import Base, get_db
from app.main import app
from app.models import Assessment, Finding, FindingReview
from app.pipeline import llm as llm_service
from app.pipeline import runner
from app.pipeline.graph import create_assessment
from app.pipeline.runner import run_assessment
from tests.test_pipeline import DOC_TEXT, QUOTE, FakeLLM, _missing_draft, _valid_draft

AI_COLUMNS = (
    "status",
    "verdict",
    "policy_quote",
    "clause_ref",
    "confidence",
    "rationale",
    "matched_chunk_id",
    "match_start",
    "match_end",
    "match_method",
    "match_score",
    "abstain_reason",
    "attempts",
    "final_model",
    "final_provider",
    "retrieved",
    "audit_log",
    "requirement_fr",
    "domain",
)


@pytest.fixture()
def client(monkeypatch):
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

    monkeypatch.setattr(runner, "launch", lambda sf, aid: True)  # no threads in tests
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[assessments_api.get_session_factory] = lambda: TestSession
    tc = TestClient(app)
    tc.session_factory = TestSession
    yield tc
    app.dependency_overrides.clear()
    llm_service.set_provider(None)


@pytest.fixture()
def reviewed_env(client):
    """Org + completed 2-requirement assessment: A.9.2 VERIFIED, A.4.5
    ABSTAINED (model_abstained). Returns (org_id, assessment_id, by_req)."""
    org_id = client.post("/api/organizations", json={"name": "Revue SA"}).json()["id"]
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique_ia.txt", DOC_TEXT.encode(), "text/plain")},
    )
    assert r.status_code == 201
    llm_service.set_provider(FakeLLM([_valid_draft(), _missing_draft(clause="A.4.5")]))
    aid = create_assessment(client.session_factory, org_id, ["A.9.2", "A.4.5"])
    run = run_assessment(client.session_factory, aid)
    assert run.status == "COMPLETED"
    db = client.session_factory()
    by_req = {
        f.requirement_id: f.id
        for f in db.scalars(select(Finding).where(Finding.assessment_id == aid))
    }
    db.close()
    return org_id, aid, by_req


def _finding_url(org_id, aid, fid) -> str:
    return f"/api/organizations/{org_id}/assessments/{aid}/findings/{fid}"


def _snapshot_ai_columns(session_factory, finding_id) -> dict:
    db = session_factory()
    row = db.get(Finding, finding_id)
    snap = {c: getattr(row, c) for c in AI_COLUMNS}
    db.close()
    return snap


# ---------------------------------------------------------------- detail GET


def test_detail_serves_snapshot_and_authoritative_source_quote(client, reviewed_env):
    org_id, aid, by_req = reviewed_env
    r = client.get(_finding_url(org_id, aid, by_req["A.9.2"]))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "VERIFIED"
    # requirement snapshot persisted by the pipeline, not live-KB hydration
    assert body["requirement_fr"] and body["corpus_mismatch"] is False
    # authoritative source slice equals the raw page slice at the offsets
    assert body["source_quote"] == QUOTE
    assert body["source_quote_error"] is None
    assert body["retrieved"]  # split-view payload
    # full attempt history with provider calls
    assert body["attempt_history"][0]["llm_calls"][0]["provider"] == "fake"
    assert body["review_status"] == "PENDING" and body["reviews"] == []


def test_detail_source_quote_fails_closed_on_corrupt_offsets(client, reviewed_env):
    org_id, aid, by_req = reviewed_env
    db = client.session_factory()
    row = db.get(Finding, by_req["A.9.2"])
    row.match_end = row.match_end + 10_000  # corrupt provenance
    db.commit()
    db.close()
    body = client.get(_finding_url(org_id, aid, by_req["A.9.2"])).json()
    assert body["source_quote"] is None
    assert "offsets de citation invalides" in body["source_quote_error"]


def test_detail_legacy_row_falls_back_to_live_kb_or_flags_mismatch(client, reviewed_env):
    org_id, aid, by_req = reviewed_env
    db = client.session_factory()
    row = db.get(Finding, by_req["A.9.2"])
    row.requirement_fr = None  # simulate a pre-0012 row
    row.domain = None
    db.commit()
    db.close()
    # corpus_version matches the live KB -> documented fallback
    body = client.get(_finding_url(org_id, aid, by_req["A.9.2"])).json()
    assert body["requirement_fr"] and body["corpus_mismatch"] is False
    # corpus_version no longer matches -> null + flag, never foreign-KB text
    db = client.session_factory()
    db.get(Assessment, aid).corpus_version = "0.9.9"
    db.commit()
    db.close()
    body = client.get(_finding_url(org_id, aid, by_req["A.9.2"])).json()
    assert body["requirement_fr"] is None and body["corpus_mismatch"] is True


def test_finding_routes_are_org_scoped(client, reviewed_env):
    org_id, aid, by_req = reviewed_env
    other = client.post("/api/organizations", json={"name": "Autre SA"}).json()["id"]
    fid = by_req["A.9.2"]
    assert client.get(_finding_url(other, aid, fid)).status_code == 404
    assert (
        client.post(
            _finding_url(other, aid, fid) + "/review", json={"action": "approve"}
        ).status_code
        == 404
    )
    # wrong assessment id in the chain
    assert client.get(_finding_url(org_id, "nope", fid)).status_code == 404


# ---------------------------------------------------------------- decisions


def test_approve_confirms_and_never_touches_ai_columns(client, reviewed_env):
    org_id, aid, by_req = reviewed_env
    fid = by_req["A.9.2"]
    before = _snapshot_ai_columns(client.session_factory, fid)
    r = client.post(
        _finding_url(org_id, aid, fid) + "/review",
        json={"action": "approve", "reviewer_label": "Y. El Gares"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "CONFIRMED"
    assert body["review_action"] == "approve"
    assert body["human_verdict"] == before["verdict"]  # snapshot of the AI verdict
    assert body["reviewed_at"] and body["review_count"] == 1
    assert body["reviews"][0]["reviewer_label"] == "Y. El Gares"
    assert _snapshot_ai_columns(client.session_factory, fid) == before
    # reviewed_count surfaces in the assessment payloads
    detail = client.get(f"/api/organizations/{org_id}/assessments/{aid}").json()
    assert detail["reviewed_count"] == 1


def test_edit_requires_rationale_and_keeps_ai_verdict(client, reviewed_env):
    org_id, aid, by_req = reviewed_env
    url = _finding_url(org_id, aid, by_req["A.9.2"]) + "/review"
    r = client.post(url, json={"action": "edit"})
    assert r.status_code == 422 and "justification" in r.json()["detail"]
    r = client.post(url, json={"action": "edit", "human_rationale": "Nuance apportée."})
    assert r.status_code == 200
    body = r.json()
    assert body["human_verdict"] == "compliant"  # AI verdict kept
    assert body["human_rationale"] == "Nuance apportée."


def test_override_requires_verdict_and_rationale(client, reviewed_env):
    org_id, aid, by_req = reviewed_env
    url = _finding_url(org_id, aid, by_req["A.9.2"]) + "/review"
    r = client.post(url, json={"action": "override", "human_verdict": "partial"})
    assert r.status_code == 422
    r = client.post(
        url,
        json={
            "action": "override",
            "human_verdict": "partial",
            "human_rationale": "La preuve ne couvre qu'une partie de l'exigence.",
        },
    )
    assert r.status_code == 200
    assert r.json()["human_verdict"] == "partial"
    # invalid verdict value -> normalized French Pydantic error
    r = client.post(
        url,
        json={"action": "override", "human_verdict": "bogus", "human_rationale": "x"},
    )
    assert r.status_code == 422 and r.json()["detail"].startswith("Requête invalide")


def test_abstained_findings_accept_only_override(client, reviewed_env):
    org_id, aid, by_req = reviewed_env
    url = _finding_url(org_id, aid, by_req["A.4.5"]) + "/review"
    for action in ("approve", "edit"):
        r = client.post(url, json={"action": action, "human_rationale": "x"})
        assert r.status_code == 422
        assert "remplacer" in r.json()["detail"]
    r = client.post(
        url,
        json={
            "action": "override",
            "human_verdict": "missing",
            "human_rationale": "Aucune preuve : écart confirmé.",
        },
    )
    assert r.status_code == 200
    assert r.json()["review_status"] == "CONFIRMED"


def test_rereview_appends_history_and_resets_stale_fields(client, reviewed_env):
    """An edit after an override restores the AI verdict and clears the stale
    note; the immutable history keeps both decisions in sequence."""
    org_id, aid, by_req = reviewed_env
    url = _finding_url(org_id, aid, by_req["A.9.2"]) + "/review"
    client.post(
        url,
        json={
            "action": "override",
            "human_verdict": "non_compliant",
            "human_rationale": "Première lecture.",
            "review_note": "à revoir",
        },
    )
    r = client.post(url, json={"action": "edit", "human_rationale": "Relecture : conforme."})
    body = r.json()
    assert body["review_count"] == 2
    assert body["review_action"] == "edit"
    assert body["human_verdict"] == "compliant"  # stale override verdict reset
    assert body["review_note"] is None  # stale note reset
    assert [rv["sequence"] for rv in body["reviews"]] == [1, 2]
    assert [rv["action"] for rv in body["reviews"]] == ["override", "edit"]
    assert body["reviews"][0]["human_verdict"] == "non_compliant"
    # history rows are immutable inserts, not updates
    db = client.session_factory()
    assert len(db.scalars(select(FindingReview)).all()) == 2
    db.close()

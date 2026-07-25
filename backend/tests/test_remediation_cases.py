"""HTTP + service tests for M7a remediation cases: eligibility, linking with
snapshots, triage draft/approve/reopen (input-revision contract), closure and
reopen (one-active-case-per-finding)."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import assessments as assessments_api
from app.api import remediation as remediation_api
from app.db import Base, get_db
from app.main import app
from app.models import (
    RemediationAttempt,
    RemediationCase,
    RemediationEvent,
    RemediationLlmCall,
    RemediationTriageDraft,
)
from app.pipeline import llm as llm_service
from app.pipeline import runner
from app.pipeline.graph import create_assessment
from app.pipeline.runner import run_assessment
from tests.test_pipeline import DOC_TEXT, FakeLLM, _missing_draft, _valid_draft


def _triage_json(scope="local") -> str:
    return json.dumps(
        {
            "classification": "evidence_gap",
            "correction_note": "Documenter la preuve manquante sans délai.",
            "scope": scope,
            "scope_rationale": "L'écart est limité à une exigence.",
        },
        ensure_ascii=False,
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

    monkeypatch.setattr(runner, "launch", lambda sf, aid: True)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[assessments_api.get_session_factory] = lambda: TestSession
    app.dependency_overrides[remediation_api.get_session_factory] = lambda: TestSession
    tc = TestClient(app)
    tc.session_factory = TestSession
    yield tc
    app.dependency_overrides.clear()
    llm_service.set_provider(None)


@pytest.fixture()
def gap_env(client):
    """Org + completed assessment with three reviewed findings:
    A.9.2 CONFIRMED partial (eligible), A.4.5 ABSTAINED PENDING,
    A.5.2 CONFIRMED compliant (NOT eligible). Returns (org_id, aid, by_req)."""
    org_id = client.post("/api/organizations", json={"name": "Remédiation SA"}).json()["id"]
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique_ia.txt", DOC_TEXT.encode(), "text/plain")},
    )
    assert r.status_code == 201
    llm_service.set_provider(
        FakeLLM(
            [
                _valid_draft(verdict="partial"),
                _missing_draft(clause="A.4.5"),
                _valid_draft(clause="A.5.2", verdict="compliant"),
            ]
        )
    )
    aid = create_assessment(client.session_factory, org_id, ["A.9.2", "A.4.5", "A.5.2"])
    assert run_assessment(client.session_factory, aid).status == "COMPLETED"
    db = client.session_factory()
    from app.models import Finding

    by_req = {
        f.requirement_id: f.id
        for f in db.scalars(select(Finding).where(Finding.assessment_id == aid))
    }
    db.close()
    base = f"/api/organizations/{org_id}/assessments/{aid}/findings"
    assert client.post(f"{base}/{by_req['A.9.2']}/review", json={"action": "approve"}).status_code == 200
    assert client.post(f"{base}/{by_req['A.5.2']}/review", json={"action": "approve"}).status_code == 200
    return org_id, aid, by_req


def _create_case(client, org_id, finding_id, scripts=None, **body):
    llm_service.set_provider(FakeLLM(scripts if scripts is not None else [_triage_json()]))
    return client.post(
        f"/api/organizations/{org_id}/remediation-cases",
        json={"finding_id": finding_id, **body},
    )


def _url(org_id, case_id="", tail=""):
    u = f"/api/organizations/{org_id}/remediation-cases"
    if case_id:
        u += f"/{case_id}"
    return u + tail


# ------------------------------------------------------------------ creation


def test_triage_corpus_changed_maps_to_retrieval_error(client, gap_env, monkeypatch):
    """The triage similar-gap search failing with CorpusChangedError (a mid-
    search version activation) is an operational abort -> the triage draft is
    ABSTAINED(retrieval_error), the case still opens (rev.6 triage mapping)."""
    from app.remediation import triage as triage_module
    from app.services.retrieval import CorpusChangedError

    org_id, _aid, by_req = gap_env

    def boom(*a, **kw):
        raise CorpusChangedError()

    monkeypatch.setattr(triage_module, "hybrid_search", boom)
    r = _create_case(client, org_id, by_req["A.9.2"])
    assert r.status_code == 201
    (draft,) = r.json()["triage_drafts"]
    assert draft["status"] == "ABSTAINED"
    assert draft["abstain_reason"] == "retrieval_error"


def test_create_case_from_confirmed_gap_finding(client, gap_env):
    org_id, _aid, by_req = gap_env
    r = _create_case(client, org_id, by_req["A.9.2"], actor_label="Aïcha")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "TRIAGE"
    assert body["evidence_revision"] == 0
    (link,) = body["finding_links"]
    assert link["is_primary"] and link["link_source"] == "creation"
    # snapshot of the review state at link time
    assert link["finding_human_verdict"] == "partial"
    assert link["finding_review_count"] == 1
    assert link["finding_requirement_fr"]
    # synchronous triage draft
    (draft,) = body["triage_drafts"]
    assert draft["status"] == "VERIFIED"
    assert draft["ai_classification"] == "evidence_gap"
    assert draft["input_evidence_revision"] == 0
    assert draft["input_finding_links"][0]["finding_id"] == by_req["A.9.2"]
    assert [e["event_type"] for e in body["events"]] == [
        "case_created",
        "finding_linked",
        "triage_drafted",
    ]
    assert [e["sequence"] for e in body["events"]] == [1, 2, 3]


def test_create_case_rejects_ineligible_findings(client, gap_env):
    org_id, _aid, by_req = gap_env
    # CONFIRMED compliant: confirmation is not a gap
    assert _create_case(client, org_id, by_req["A.5.2"]).status_code == 422
    # PENDING (not yet reviewed)
    assert _create_case(client, org_id, by_req["A.4.5"]).status_code == 422
    # unknown finding
    assert _create_case(client, org_id, "nope").status_code == 404
    # cross-org
    other = client.post("/api/organizations", json={"name": "Autre SA"}).json()["id"]
    assert _create_case(client, other, by_req["A.9.2"]).status_code == 404


def test_one_active_case_per_finding(client, gap_env):
    org_id, _aid, by_req = gap_env
    assert _create_case(client, org_id, by_req["A.9.2"]).status_code == 201
    assert _create_case(client, org_id, by_req["A.9.2"]).status_code == 409


def test_triage_abstains_on_provider_failure_and_schema_invalid(client, gap_env):
    org_id, _aid, by_req = gap_env
    # all providers failed -> llm_error, case still created (201)
    r = _create_case(client, org_id, by_req["A.9.2"], scripts=[None])
    assert r.status_code == 201
    (draft,) = r.json()["triage_drafts"]
    assert draft["status"] == "ABSTAINED" and draft["abstain_reason"] == "llm_error"
    # close it so the finding is free again
    case_id = r.json()["id"]
    client.post(_url(org_id, case_id, "/triage/reopen"), json={})  # not approved: 409, ignore
    db = client.session_factory()
    case = db.get(RemediationCase, case_id)
    # malformed JSON twice -> schema_invalid with 2 attempts + calls persisted
    llm_service.set_provider(FakeLLM(["not json", "still not json"]))
    from app.remediation.triage import draft_triage

    d2 = draft_triage(db, org_id, case_id)
    assert d2.status == "ABSTAINED" and d2.abstain_reason == "schema_invalid"
    assert d2.draft_attempts == 2 and d2.sequence == 2
    attempts = db.scalars(
        select(RemediationAttempt).where(RemediationAttempt.triage_draft_id == d2.id)
    ).all()
    assert [a.attempt_number for a in attempts] == [1, 2]
    calls = db.scalars(select(RemediationLlmCall)).all()
    assert len(calls) >= 2
    db.close()


# ------------------------------------------------------------------- linking


def test_link_reject_unlink_and_revision_bumps(client, gap_env):
    org_id, aid, by_req = gap_env
    case_id = _create_case(client, org_id, by_req["A.9.2"]).json()["id"]
    # make A.4.5 eligible (override its abstention as a missing gap)
    base = f"/api/organizations/{org_id}/assessments/{aid}/findings"
    r = client.post(
        f"{base}/{by_req['A.4.5']}/review",
        json={"action": "override", "human_verdict": "missing", "human_rationale": "Aucune preuve."},
    )
    assert r.status_code == 200

    # reject: provenance event only, no link, no revision bump
    r = client.post(
        _url(org_id, case_id, "/findings"),
        json={"finding_id": by_req["A.4.5"], "decision": "reject", "link_note": "hors sujet"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["finding_links"]) == 1 and body["evidence_revision"] == 0
    assert body["events"][-1]["event_type"] == "finding_link_rejected"

    # link: revision bumps, snapshot recorded
    r = client.post(
        _url(org_id, case_id, "/findings"),
        json={"finding_id": by_req["A.4.5"], "decision": "link", "link_source": "search_suggested"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["finding_links"]) == 2 and body["evidence_revision"] == 1
    new_link = next(l for l in body["finding_links"] if not l["is_primary"])
    assert new_link["finding_human_verdict"] == "missing"

    # duplicate link -> 409 ; compliant finding -> 422
    assert client.post(
        _url(org_id, case_id, "/findings"),
        json={"finding_id": by_req["A.4.5"], "decision": "link"},
    ).status_code == 409
    assert client.post(
        _url(org_id, case_id, "/findings"),
        json={"finding_id": by_req["A.5.2"], "decision": "link"},
    ).status_code == 422

    # unlink non-primary bumps again; primary unlink refused
    r = client.delete(_url(org_id, case_id, f"/findings/{by_req['A.4.5']}"))
    assert r.status_code == 200 and r.json()["evidence_revision"] == 2
    assert client.delete(
        _url(org_id, case_id, f"/findings/{by_req['A.9.2']}")
    ).status_code == 422


def test_link_suggestions_lists_eligible_unlinked_findings(client, gap_env):
    org_id, aid, by_req = gap_env
    case_id = _create_case(client, org_id, by_req["A.9.2"]).json()["id"]
    base = f"/api/organizations/{org_id}/assessments/{aid}/findings"
    client.post(
        f"{base}/{by_req['A.4.5']}/review",
        json={"action": "override", "human_verdict": "missing", "human_rationale": "Aucune preuve."},
    )
    r = client.get(_url(org_id, case_id, "/link-suggestions"))
    assert r.status_code == 200
    ids = [s["finding_id"] for s in r.json()]
    assert by_req["A.4.5"] in ids  # eligible, unlinked
    assert by_req["A.9.2"] not in ids  # already linked
    assert by_req["A.5.2"] not in ids  # compliant: never suggested

    # A finding owned by ANOTHER active case is refused at link time
    # (one active case per finding): suggesting it would be a guaranteed 409.
    other_case = _create_case(client, org_id, by_req["A.4.5"])
    assert other_case.status_code == 201
    r = client.get(_url(org_id, case_id, "/link-suggestions"))
    assert r.status_code == 200
    assert by_req["A.4.5"] not in [s["finding_id"] for s in r.json()]
    # …and it comes back once that case is CLOSED (linking is legal again)
    other_id = other_case.json()["id"]
    client.post(
        _url(org_id, other_id, "/triage/approve"),
        json={"triage_draft_id": other_case.json()["triage_drafts"][0]["id"]},
    )
    assert client.post(
        _url(org_id, other_id, "/close"), json={"close_note": "doublon"}
    ).status_code == 200
    r = client.get(_url(org_id, case_id, "/link-suggestions"))
    assert by_req["A.4.5"] in [s["finding_id"] for s in r.json()]


# ---------------------------------------------------- triage approval / reopen


def test_approve_triage_explicit_draft_with_overrides(client, gap_env):
    org_id, _aid, by_req = gap_env
    body = _create_case(client, org_id, by_req["A.9.2"]).json()
    case_id, draft_id = body["id"], body["triage_drafts"][0]["id"]
    r = client.post(
        _url(org_id, case_id, "/triage/approve"),
        json={
            "triage_draft_id": draft_id,
            "scope": "related_requirements",
            "reviewer_label": "Aïcha",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "TRIAGE_APPROVED"
    assert body["classification"] == "evidence_gap"  # accepted from the draft
    assert body["scope"] == "related_requirements"  # human override
    assert body["approved_triage_draft_id"] == draft_id
    approved = next(e for e in body["events"] if e["event_type"] == "triage_approved")
    assert approved["payload"]["overridden_fields"] == ["scope"]
    # links are frozen after approval: 409 instructs to reopen triage
    assert client.post(
        _url(org_id, case_id, "/findings"),
        json={"finding_id": by_req["A.4.5"], "decision": "link"},
    ).status_code == 409


def test_stale_triage_draft_rejected_after_link(client, gap_env):
    org_id, aid, by_req = gap_env
    body = _create_case(client, org_id, by_req["A.9.2"]).json()
    case_id, draft_id = body["id"], body["triage_drafts"][0]["id"]
    base = f"/api/organizations/{org_id}/assessments/{aid}/findings"
    client.post(
        f"{base}/{by_req['A.4.5']}/review",
        json={"action": "override", "human_verdict": "missing", "human_rationale": "Aucune preuve."},
    )
    client.post(
        _url(org_id, case_id, "/findings"),
        json={"finding_id": by_req["A.4.5"], "decision": "link"},
    )
    # the pre-link draft no longer matches evidence_revision -> 409
    r = client.post(
        _url(org_id, case_id, "/triage/approve"), json={"triage_draft_id": draft_id}
    )
    assert r.status_code == 409


def test_late_triage_draft_discarded_when_links_changed_mid_draft(client, gap_env):
    """Simulates link-during-draft: the drafter snapshotted revision 0, a link
    lands before persistence — the late result is discarded (409), no row."""
    org_id, aid, by_req = gap_env
    body = _create_case(client, org_id, by_req["A.9.2"]).json()
    case_id = body["id"]
    base = f"/api/organizations/{org_id}/assessments/{aid}/findings"
    client.post(
        f"{base}/{by_req['A.4.5']}/review",
        json={"action": "override", "human_verdict": "missing", "human_rationale": "Aucune preuve."},
    )

    from app.remediation import triage as triage_module
    from app.remediation.service import RemediationConflictError

    class LinkDuringDraft:
        """Fake provider that links a finding while the LLM call is in flight."""

        def complete_json(self, messages, *, json_schema=None, schema_name="x", on_call_finished=None):
            r = client.post(
                _url(org_id, case_id, "/findings"),
                json={"finding_id": by_req["A.4.5"], "decision": "link"},
            )
            assert r.status_code == 200
            return llm_service.LLMOutcome(content=_triage_json(), calls=[])

    llm_service.set_provider(LinkDuringDraft())
    db = client.session_factory()
    with pytest.raises(RemediationConflictError):
        triage_module.draft_triage(db, org_id, case_id)
    drafts = db.scalars(
        select(RemediationTriageDraft).where(RemediationTriageDraft.case_id == case_id)
    ).all()
    assert len(drafts) == 1  # only the creation-time draft; no stale row
    db.close()


def test_abstained_draft_approval_requires_the_three_mandatory_fields(client, gap_env):
    """An ABSTAINED draft carries no AI values, so the human must supply
    classification, scope and scope_rationale. correction_note is deliberately
    NOT in that set: it records the IMMEDIATE correction, which may legitimately
    be empty, and ck_remediation_cases_triage_coherence leaves it nullable for
    exactly that reason."""
    org_id, _aid, by_req = gap_env
    body = _create_case(client, org_id, by_req["A.9.2"], scripts=[None]).json()
    case_id, draft_id = body["id"], body["triage_drafts"][0]["id"]
    r = client.post(
        _url(org_id, case_id, "/triage/approve"), json={"triage_draft_id": draft_id}
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "classification" in detail and "scope" in detail
    assert "correction_note" not in detail

    # the three mandatory fields alone are enough — no invented correction text
    r = client.post(
        _url(org_id, case_id, "/triage/approve"),
        json={
            "triage_draft_id": draft_id,
            "classification": "nonconformity",
            "scope": "local",
            "scope_rationale": "Écart isolé.",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "TRIAGE_APPROVED"
    assert r.json()["correction_note"] is None


def test_blank_correction_note_clears_the_ai_value(client, gap_env):
    """An explicit blank is an audited human decision to record NO immediate
    correction — it must clear the AI draft's note, not silently inherit it."""
    org_id, _aid, by_req = gap_env
    body = _create_case(client, org_id, by_req["A.9.2"]).json()
    case_id, draft_id = body["id"], body["triage_drafts"][0]["id"]
    assert body["triage_drafts"][0]["ai_correction_note"]  # the AI proposed one
    r = client.post(
        _url(org_id, case_id, "/triage/approve"),
        json={"triage_draft_id": draft_id, "correction_note": "   "},
    )
    assert r.status_code == 200
    assert r.json()["correction_note"] is None


def test_reopen_triage_clears_projection_and_bumps_revision(client, gap_env):
    org_id, _aid, by_req = gap_env
    body = _create_case(client, org_id, by_req["A.9.2"]).json()
    case_id, draft_id = body["id"], body["triage_drafts"][0]["id"]
    client.post(_url(org_id, case_id, "/triage/approve"), json={"triage_draft_id": draft_id})
    r = client.post(_url(org_id, case_id, "/triage/reopen"), json={"actor_label": "Aïcha"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "TRIAGE"
    assert body["classification"] is None and body["approved_triage_draft_id"] is None
    assert body["evidence_revision"] == 1
    reopened = next(e for e in body["events"] if e["event_type"] == "triage_reopened")
    assert reopened["payload"]["before"]["classification"] == "evidence_gap"
    # redraft now works and appends sequence 2 with the new revision
    llm_service.set_provider(FakeLLM([_triage_json()]))
    r = client.post(_url(org_id, case_id, "/triage/redraft"), json={})
    assert r.status_code == 200
    assert r.json()["sequence"] == 2 and r.json()["input_evidence_revision"] == 1


# ------------------------------------------------------------- close / reopen


def test_close_requires_note_and_valid_source_state(client, gap_env):
    org_id, _aid, by_req = gap_env
    body = _create_case(client, org_id, by_req["A.9.2"]).json()
    case_id, draft_id = body["id"], body["triage_drafts"][0]["id"]
    # TRIAGE: closure refused
    assert client.post(
        _url(org_id, case_id, "/close"), json={"close_note": "n"}
    ).status_code == 409
    client.post(_url(org_id, case_id, "/triage/approve"), json={"triage_draft_id": draft_id})
    # empty note refused
    assert client.post(
        _url(org_id, case_id, "/close"), json={"close_note": "  "}
    ).status_code == 422
    r = client.post(_url(org_id, case_id, "/close"), json={"close_note": "Traité hors outil."})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "CLOSED" and body["close_note"] == "Traité hors outil."


def test_reopen_restores_state_and_respects_one_active_case(client, gap_env):
    org_id, _aid, by_req = gap_env
    body = _create_case(client, org_id, by_req["A.9.2"]).json()
    case_id, draft_id = body["id"], body["triage_drafts"][0]["id"]
    client.post(_url(org_id, case_id, "/triage/approve"), json={"triage_draft_id": draft_id})
    client.post(_url(org_id, case_id, "/close"), json={"close_note": "ok"})

    # a NEW case for the same finding is now legal
    r2 = _create_case(client, org_id, by_req["A.9.2"])
    assert r2.status_code == 201
    # reopening the first case would violate one-active-case-per-finding
    assert client.post(_url(org_id, case_id, "/reopen"), json={}).status_code == 409
    # close the new case: reopen now restores TRIAGE_APPROVED and clears closure
    new_id, new_draft = r2.json()["id"], r2.json()["triage_drafts"][0]["id"]
    client.post(_url(org_id, new_id, "/triage/approve"), json={"triage_draft_id": new_draft})
    client.post(_url(org_id, new_id, "/close"), json={"close_note": "doublon"})
    r = client.post(_url(org_id, case_id, "/reopen"), json={})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "TRIAGE_APPROVED"
    assert body["closed_at"] is None and body["close_note"] is None
    reopened = next(e for e in body["events"] if e["event_type"] == "case_reopened")
    assert reopened["payload"]["previous_close_note"] == "ok"


def test_events_are_monotonic_and_payloads_validated(client, gap_env):
    org_id, _aid, by_req = gap_env
    body = _create_case(client, org_id, by_req["A.9.2"]).json()
    case_id, draft_id = body["id"], body["triage_drafts"][0]["id"]
    client.post(_url(org_id, case_id, "/triage/approve"), json={"triage_draft_id": draft_id})
    client.post(_url(org_id, case_id, "/close"), json={"close_note": "fin"})
    db = client.session_factory()
    events = db.scalars(
        select(RemediationEvent)
        .where(RemediationEvent.case_id == case_id)
        .order_by(RemediationEvent.sequence)
    ).all()
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    assert all(e.payload_version == 1 for e in events)
    db.close()


def test_unlink_records_the_actor_like_every_sibling_event(client, gap_env):
    """Audit pass 5 (F7): `unlink_finding` is the only mutation in this router
    that is a DELETE, so it had no RemediationActorBody to read — and the
    route simply never passed `actor_label`, even though the service accepts
    it and writes it. `finding_unlinked` was the one event in the whole case
    stream that silently lost its attribution."""
    org_id, aid, by_req = gap_env
    case_id = _create_case(client, org_id, by_req["A.9.2"]).json()["id"]
    client.post(
        f"/api/organizations/{org_id}/assessments/{aid}/findings/{by_req['A.4.5']}/review",
        json={
            "action": "override",
            "human_verdict": "missing",
            "human_rationale": "Aucune preuve.",
        },
    )
    client.post(
        _url(org_id, case_id, "/findings"),
        json={
            "finding_id": by_req["A.4.5"],
            "decision": "link",
            "actor_label": "Alice",
        },
    )

    r = client.delete(
        _url(org_id, case_id, f"/findings/{by_req['A.4.5']}"), params={"actor_label": "Alice"}
    )
    assert r.status_code == 200
    unlinked = [e for e in r.json()["events"] if e["event_type"] == "finding_unlinked"]
    assert len(unlinked) == 1
    assert unlinked[0]["actor_label"] == "Alice"
    # linked and unlinked now carry attribution the same way
    linked = [e for e in r.json()["events"] if e["event_type"] == "finding_linked"]
    assert linked[-1]["actor_label"] == "Alice"


def test_unlink_without_an_actor_stays_anonymous_rather_than_failing(client, gap_env):
    """The label is optional everywhere else (free text, explicitly unverified
    — there is no identity layer by design), so it stays optional here."""
    org_id, aid, by_req = gap_env
    case_id = _create_case(client, org_id, by_req["A.9.2"]).json()["id"]
    client.post(
        f"/api/organizations/{org_id}/assessments/{aid}/findings/{by_req['A.4.5']}/review",
        json={
            "action": "override",
            "human_verdict": "missing",
            "human_rationale": "Aucune preuve.",
        },
    )
    client.post(
        _url(org_id, case_id, "/findings"),
        json={"finding_id": by_req["A.4.5"], "decision": "link"},
    )
    r = client.delete(_url(org_id, case_id, f"/findings/{by_req['A.4.5']}"))
    assert r.status_code == 200
    unlinked = [e for e in r.json()["events"] if e["event_type"] == "finding_unlinked"]
    assert unlinked[0]["actor_label"] is None

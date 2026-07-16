"""Action review windows, lifecycle matrix, effectiveness, active-plan
authority and the reassessment launch protocol (M7a steps 3-4)."""

import pytest
from sqlalchemy import select

from app.models import (
    Assessment,
    RemediationAction,
    RemediationActionRequirement,
    RemediationCase,
    RemediationReassessment,
)
from app.pipeline import llm as llm_service
from app.pipeline import runner
from app.pipeline.dev_split import DEV_REQUIREMENT_IDS
from app.pipeline.runner import run_assessment
from app.services.retrieval import load_kb
from tests.test_pipeline import FakeLLM, _valid_draft
from tests.test_remediation_cases import (  # noqa: F401 — shared fixtures
    _create_case,
    _url,
    client,
    gap_env,
)
from tests.test_remediation_planner import (  # noqa: F401 — shared fixtures
    DynamicFake,
    _plan_json,
    _post_plan,
    approved_case,
)

AI_COLUMNS = (
    "action_type",
    "ai_description",
    "ai_rationale",
    "ai_owner_role",
    "ai_success_criterion",
    "ai_impacted_requirement_ids",
    "policy_quote",
    "matched_chunk_id",
    "match_method",
)


def _holdout_id() -> str:
    kb = load_kb()
    return sorted(set(kb["by_id"]) - set(DEV_REQUIREMENT_IDS))[0]


@pytest.fixture()
def plan_case(client, approved_case):
    """approved_case + a VERIFIED active plan with one action on A.9.2.
    Returns (org_id, case_id, action_id)."""
    org_id, case_id = approved_case
    llm_service.set_provider(DynamicFake([_plan_json()]))
    plan = _post_plan(client, org_id, case_id).json()
    assert plan["status"] == "VERIFIED"
    return org_id, case_id, plan["actions"][0]["id"]


def _review(client, org_id, case_id, action_id, **body):
    # 0018: IN_PROGRESS requires a human-set deadline; default one on
    # approve/edit so lifecycle-focused tests stay readable (the launch gate
    # itself is covered by test_in_progress_requires_due_date).
    if body.get("action") in ("approve", "edit") and "due_date" not in body:
        body["due_date"] = "2026-09-30"
    return client.post(
        _url(org_id, case_id, f"/actions/{action_id}/review"), json=body
    )


def _lifecycle(client, org_id, case_id, action_id, target):
    return client.post(
        _url(org_id, case_id, f"/actions/{action_id}/lifecycle"),
        json={"lifecycle": target},
    )


def _to_done(client, org_id, case_id, action_id):
    assert _review(
        client, org_id, case_id, action_id, action="approve", priority="haute"
    ).status_code == 200
    assert _lifecycle(client, org_id, case_id, action_id, "IN_PROGRESS").status_code == 200
    assert _lifecycle(client, org_id, case_id, action_id, "DONE").status_code == 200


# ------------------------------------------------------------------- review


def test_action_mutation_blocked_while_case_planning(client, plan_case):
    """Finding 1 TOCTOU: while a draft holds the case in PLANNING (its lock is
    released during the LLM phase), a concurrent request must not mutate an
    active-plan action — otherwise phase 3 supersedes the just-approved action
    into inert history. _operable_action rejects with 409; PLAN_READY works."""
    org_id, case_id, action_id = plan_case

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    db = client.session_factory()
    case = db.get(RemediationCase, case_id)
    assert case.status == "PLAN_READY"
    # a coherent live PLANNING lease (ck_remediation_cases_lease_coherence)
    case.status = "PLANNING"
    case.planning_token = "jeton-concurrent"
    case.planning_started_at = now
    case.planning_heartbeat_at = now
    db.commit()
    db.close()

    r = _review(client, org_id, case_id, action_id, action="approve", priority="haute")
    assert r.status_code == 409
    assert "Rédaction de plan en cours" in r.text

    # the very same approval succeeds once drafting has finished (PLAN_READY)
    db = client.session_factory()
    case = db.get(RemediationCase, case_id)
    case.status = "PLAN_READY"
    case.planning_token = None
    case.planning_started_at = None
    case.planning_heartbeat_at = None
    db.commit()
    db.close()
    assert _review(
        client, org_id, case_id, action_id, action="approve", priority="haute"
    ).status_code == 200


def test_approve_requires_priority_and_snapshots_ai_values(client, plan_case):
    org_id, case_id, action_id = plan_case
    assert _review(client, org_id, case_id, action_id, action="approve").status_code == 422
    r = _review(
        client, org_id, case_id, action_id,
        action="approve", priority="haute", reviewer_label="Aïcha",
    )
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "CONFIRMED" and body["lifecycle"] == "APPROVED"
    assert body["description"] == body["ai_description"]
    assert body["priority"] == "haute"
    # effective requirement scope snapshotted from the AI proposal
    db = client.session_factory()
    reqs = db.scalars(
        select(RemediationActionRequirement).where(
            RemediationActionRequirement.action_id == action_id
        )
    ).all()
    assert [r_.requirement_id for r_ in reqs] == ["A.9.2"]
    assert all(r_.requirement_fr for r_ in reqs)  # KB snapshot, not just the id
    db.close()
    # first review moves the case to IN_PROGRESS
    assert client.get(_url(org_id, case_id)).json()["status"] == "IN_PROGRESS"


def test_edit_overrides_scope_and_records_override(client, plan_case):
    org_id, case_id, action_id = plan_case
    holdout = _holdout_id()
    r = _review(
        client, org_id, case_id, action_id,
        action="edit", priority="normale",
        description="Version humaine de l'action.",
        impacted_requirement_ids=["A.9.2", holdout],
    )
    assert r.status_code == 200
    body = r.json()
    assert body["description"] == "Version humaine de l'action."
    assert body["rationale"] == body["ai_rationale"]  # omitted: AI value kept
    detail = client.get(_url(org_id, case_id)).json()
    event = next(e for e in detail["events"] if e["event_type"] == "action_reviewed")
    assert event["payload"]["requirement_override"] is True
    assert sorted(event["payload"]["effective_requirement_ids"]) == sorted(
        ["A.9.2", holdout]
    )
    # invalid scopes rejected
    for bad in ([], ["A.9.2", "A.9.2"], ["X.99.9"]):
        assert _review(
            client, org_id, case_id, action_id,
            action="edit", priority="normale", impacted_requirement_ids=bad,
        ).status_code == 422


def test_reject_clears_effective_fields_and_terminates(client, plan_case):
    org_id, case_id, action_id = plan_case
    r = _review(client, org_id, case_id, action_id, action="reject", review_note="Refusée.")
    assert r.status_code == 200
    body = r.json()
    assert body["lifecycle"] == "REJECTED" and body["description"] is None
    db = client.session_factory()
    assert (
        db.scalars(
            select(RemediationActionRequirement).where(
                RemediationActionRequirement.action_id == action_id
            )
        ).all()
        == []
    )
    db.close()
    # terminal: no further review or lifecycle change
    assert _review(
        client, org_id, case_id, action_id, action="approve", priority="haute"
    ).status_code == 409
    assert _lifecycle(client, org_id, case_id, action_id, "IN_PROGRESS").status_code == 409


def test_re_review_with_omitted_scope_preserves_the_human_decision(client, plan_case):
    """An omitted impacted_requirement_ids on re-review keeps the CURRENT
    effective rows — it never silently reverts to the AI proposal — and the
    action payload exposes the authoritative effective scope."""
    org_id, case_id, action_id = plan_case
    holdout = _holdout_id()
    r = _review(
        client, org_id, case_id, action_id,
        action="edit", priority="haute",
        impacted_requirement_ids=["A.9.2", holdout],
    )
    assert sorted(r.json()["effective_requirement_ids"]) == sorted(["A.9.2", holdout])
    # re-review WITHOUT ids: human scope preserved, override still recorded
    r = _review(client, org_id, case_id, action_id, action="approve", priority="normale")
    assert r.status_code == 200
    assert sorted(r.json()["effective_requirement_ids"]) == sorted(["A.9.2", holdout])
    detail = client.get(_url(org_id, case_id)).json()
    last_review = [
        e for e in detail["events"] if e["event_type"] == "action_reviewed"
    ][-1]
    assert last_review["payload"]["requirement_override"] is True
    # explicit ids still replace
    r = _review(
        client, org_id, case_id, action_id,
        action="edit", priority="haute", impacted_requirement_ids=["A.9.2"],
    )
    assert r.json()["effective_requirement_ids"] == ["A.9.2"]


def test_re_review_only_while_approved_and_write_once_ai(client, plan_case):
    org_id, case_id, action_id = plan_case
    _review(client, org_id, case_id, action_id, action="approve", priority="haute")
    db = client.session_factory()
    before = {c: getattr(db.get(RemediationAction, action_id), c) for c in AI_COLUMNS}
    db.close()
    # re-review while APPROVED: edit replaces the projection
    r = _review(
        client, org_id, case_id, action_id,
        action="edit", priority="basse", description="Révisée.",
    )
    assert r.status_code == 200 and r.json()["review_count"] == 2
    db = client.session_factory()
    after = {c: getattr(db.get(RemediationAction, action_id), c) for c in AI_COLUMNS}
    db.close()
    assert after == before  # AI columns untouched by any review
    # once IN_PROGRESS: review window closed
    _lifecycle(client, org_id, case_id, action_id, "IN_PROGRESS")
    assert _review(
        client, org_id, case_id, action_id, action="edit", priority="haute"
    ).status_code == 409


def test_lifecycle_matrix(client, plan_case):
    org_id, case_id, action_id = plan_case
    # PROPOSED: lifecycle endpoint never applies (review owns it)
    assert _lifecycle(client, org_id, case_id, action_id, "IN_PROGRESS").status_code == 409
    _review(client, org_id, case_id, action_id, action="approve", priority="haute")
    assert _lifecycle(client, org_id, case_id, action_id, "DONE").status_code == 409
    assert _lifecycle(client, org_id, case_id, action_id, "IN_PROGRESS").status_code == 200
    assert _lifecycle(client, org_id, case_id, action_id, "DONE").status_code == 200
    # DONE is terminal for the lifecycle endpoint
    assert _lifecycle(client, org_id, case_id, action_id, "CANCELLED").status_code == 409


def test_effectiveness_only_on_done_with_note(client, plan_case):
    org_id, case_id, action_id = plan_case
    url = _url(org_id, case_id, f"/actions/{action_id}/effectiveness")
    _review(client, org_id, case_id, action_id, action="approve", priority="haute")
    assert client.post(
        url, json={"effectiveness": "EFFECTIVE", "note": "n"}
    ).status_code == 409  # APPROVED, not DONE
    _lifecycle(client, org_id, case_id, action_id, "IN_PROGRESS")
    _lifecycle(client, org_id, case_id, action_id, "DONE")
    assert client.post(
        url, json={"effectiveness": "EFFECTIVE", "note": "  "}
    ).status_code == 422
    r = client.post(
        url, json={"effectiveness": "PARTIALLY_EFFECTIVE", "note": "Preuve externe."}
    )
    assert r.status_code == 200
    assert r.json()["effectiveness"] == "PARTIALLY_EFFECTIVE"
    # re-recordable, history in events
    r = client.post(url, json={"effectiveness": "EFFECTIVE", "note": "Confirmé."})
    assert r.status_code == 200 and r.json()["effectiveness"] == "EFFECTIVE"


# --------------------------------------------------- active-plan authority


def test_superseded_plan_actions_are_inert_and_do_not_block_closure(client, plan_case):
    org_id, case_id, old_action = plan_case
    # redraft: plan 2 supersedes plan 1 (all its actions still PROPOSED)
    llm_service.set_provider(DynamicFake([_plan_json()]))
    p2 = _post_plan(client, org_id, case_id).json()
    assert p2["status"] == "VERIFIED"
    new_action = p2["actions"][0]["id"]
    # old action: inert (409), structurally rejected
    assert _review(
        client, org_id, case_id, old_action, action="approve", priority="haute"
    ).status_code == 409
    assert _lifecycle(client, org_id, case_id, old_action, "IN_PROGRESS").status_code == 409
    # foreign-case action id: structural 404
    assert _review(
        client, org_id, case_id, "action-inexistante", action="approve", priority="haute"
    ).status_code == 404
    # superseded PROPOSED actions never block closure; active-plan ones do
    _review(client, org_id, case_id, new_action, action="approve", priority="haute")
    assert client.post(
        _url(org_id, case_id, "/close"), json={"close_note": "n"}
    ).status_code == 409  # active APPROVED action blocks
    _lifecycle(client, org_id, case_id, new_action, "IN_PROGRESS")
    _lifecycle(client, org_id, case_id, new_action, "DONE")
    r = client.post(_url(org_id, case_id, "/close"), json={"close_note": "Terminé."})
    assert r.status_code == 200  # old plan's PROPOSED action did not block


# ------------------------------------------------------------ reassessment


def test_reassessment_launch_protocol(client, plan_case):
    org_id, case_id, action_id = plan_case
    url = _url(org_id, case_id, "/reassessments")
    # PLAN_READY (no action reviewed yet): status guard fires first
    assert client.post(url, json={"selected_action_ids": [action_id]}).status_code == 409
    _to_done(client, org_id, case_id, action_id)
    assert client.post(url, json={"selected_action_ids": []}).status_code == 422
    assert client.post(
        url, json={"selected_action_ids": ["inconnue"]}
    ).status_code == 404
    r = client.post(url, json={"selected_action_ids": [action_id]})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "LAUNCHED"
    assert body["included_requirement_ids"] == ["A.9.2"]
    assert body["excluded_holdout_ids"] == []
    assert body["assessment_id"] == body["planned_assessment_id"]
    db = client.session_factory()
    assessment = db.get(Assessment, body["assessment_id"])
    assert assessment.requirement_ids == ["A.9.2"]
    db.close()
    # repeated reassessment appends a second record
    r2 = client.post(url, json={"selected_action_ids": [action_id]})
    assert r2.status_code in (202, 409)  # 409 if the first is still RUNNING
    detail = client.get(url).json()
    assert len(detail) == 2


def test_reassessment_conflict_marks_launch_failed(client, plan_case):
    org_id, case_id, action_id = plan_case
    _to_done(client, org_id, case_id, action_id)
    # occupy the one-RUNNING-per-org slot
    from app.pipeline.graph import create_assessment

    create_assessment(client.session_factory, org_id, ["A.9.2"])
    r = client.post(
        _url(org_id, case_id, "/reassessments"),
        json={"selected_action_ids": [action_id]},
    )
    assert r.status_code == 409
    db = client.session_factory()
    (record,) = db.scalars(
        select(RemediationReassessment).where(RemediationReassessment.case_id == case_id)
    ).all()
    assert record.status == "LAUNCH_FAILED" and record.error
    db.close()


def test_reassessment_zero_dev_scope_rejected(client, plan_case):
    org_id, case_id, action_id = plan_case
    holdout = _holdout_id()
    _review(
        client, org_id, case_id, action_id,
        action="edit", priority="haute", impacted_requirement_ids=[holdout],
    )
    _lifecycle(client, org_id, case_id, action_id, "IN_PROGRESS")
    _lifecycle(client, org_id, case_id, action_id, "DONE")
    r = client.post(
        _url(org_id, case_id, "/reassessments"),
        json={"selected_action_ids": [action_id]},
    )
    assert r.status_code == 422
    assert "jeu de test" in r.json()["detail"]


def test_effectiveness_citing_reassessment_validates_evidence(client, plan_case):
    org_id, case_id, action_id = plan_case
    holdout = _holdout_id()
    # mixed dev/holdout scope: reassessment covers the dev intersection only
    _review(
        client, org_id, case_id, action_id,
        action="edit", priority="haute",
        impacted_requirement_ids=["A.9.2", holdout],
    )
    _lifecycle(client, org_id, case_id, action_id, "IN_PROGRESS")
    _lifecycle(client, org_id, case_id, action_id, "DONE")
    r = client.post(
        _url(org_id, case_id, "/reassessments"),
        json={"selected_action_ids": [action_id]},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["included_requirement_ids"] == ["A.9.2"]
    assert body["excluded_holdout_ids"] == [holdout]

    eff_url = _url(org_id, case_id, f"/actions/{action_id}/effectiveness")
    payload = {
        "effectiveness": "EFFECTIVE",
        "note": "Réévaluation favorable.",
        "reassessment_id": body["id"],
    }
    # linked assessment still RUNNING: not usable as evidence yet
    assert client.post(eff_url, json=payload).status_code == 422
    # complete the reassessment run for real
    llm_service.set_provider(FakeLLM([_valid_draft()]))
    assert run_assessment(client.session_factory, body["assessment_id"]).status == "COMPLETED"
    r = client.post(eff_url, json=payload)
    assert r.status_code == 200
    assert r.json()["effectiveness"] == "EFFECTIVE"
    # a reassessment that never selected the action is rejected
    assert client.post(
        eff_url,
        json={**payload, "reassessment_id": "autre"},
    ).status_code == 404


def test_pending_reassessment_reconciled_after_crash(client, plan_case, monkeypatch):
    """Crash between create_assessment and the linkage write: reconciliation
    reconnects by planned_assessment_id and marks LAUNCHED."""
    org_id, case_id, action_id = plan_case
    _to_done(client, org_id, case_id, action_id)

    from app.remediation import reassessment as reassessment_module

    # simulate the crash: PENDING record + assessment created, no linkage
    import uuid as uuid_module

    from app.pipeline.graph import create_assessment

    planned = str(uuid_module.uuid4())
    db = client.session_factory()
    db.add(
        RemediationReassessment(
            case_id=case_id,
            planned_assessment_id=planned,
            selected_action_ids=[action_id],
            included_requirement_ids=["A.9.2"],
            excluded_holdout_ids=[],
            status="PENDING",
        )
    )
    db.commit()
    db.close()
    create_assessment(client.session_factory, org_id, ["A.9.2"], assessment_id=planned)

    r = client.get(_url(org_id, case_id, "/reassessments"))
    assert r.status_code == 200
    (record,) = r.json()
    assert record["status"] == "LAUNCHED"
    assert record["assessment_id"] == planned


def test_pending_without_assessment_is_resumed_under_its_planned_id(client, plan_case):
    """Crash BEFORE create_assessment: reconciliation resumes THIS record —
    the assessment is created under the recorded planned id and manifest,
    then launched. The record is never orphaned behind a fresh launch."""
    org_id, case_id, action_id = plan_case
    _to_done(client, org_id, case_id, action_id)
    planned = "id-planifie-jamais-cree"
    db = client.session_factory()
    db.add(
        RemediationReassessment(
            case_id=case_id,
            planned_assessment_id=planned,
            selected_action_ids=[action_id],
            included_requirement_ids=["A.9.2"],
            excluded_holdout_ids=[],
            status="PENDING",
        )
    )
    db.commit()
    db.close()
    (record,) = client.get(_url(org_id, case_id, "/reassessments")).json()
    assert record["status"] == "LAUNCHED"
    assert record["assessment_id"] == planned
    db = client.session_factory()
    assessment = db.get(Assessment, planned)
    assert assessment is not None and assessment.requirement_ids == ["A.9.2"]
    db.close()


def test_pending_resume_blocked_by_running_org_stays_pending(client, plan_case):
    """Crash-before-create with another assessment RUNNING: the resume is
    transient-blocked and the record stays PENDING for the next
    reconciliation — never LAUNCH_FAILED for a temporary conflict."""
    org_id, case_id, action_id = plan_case
    _to_done(client, org_id, case_id, action_id)
    from app.pipeline.graph import create_assessment

    create_assessment(client.session_factory, org_id, ["A.9.2"])  # occupies the slot
    db = client.session_factory()
    db.add(
        RemediationReassessment(
            case_id=case_id,
            planned_assessment_id="planifie-bloque",
            selected_action_ids=[action_id],
            included_requirement_ids=["A.9.2"],
            excluded_holdout_ids=[],
            status="PENDING",
        )
    )
    db.commit()
    db.close()
    (record,) = client.get(_url(org_id, case_id, "/reassessments")).json()
    assert record["status"] == "PENDING"


def test_finalize_is_idempotent_pending_cas(client, plan_case):
    """A stale second finalizer (concurrent reconciler under the same case
    lock) must not rewrite the terminal status nor append a duplicate
    reassessment_launched event — PENDING -> terminal is a compare-and-set."""
    from app.remediation import reassessment as reassessment_module

    org_id, case_id, action_id = plan_case
    _to_done(client, org_id, case_id, action_id)

    db = client.session_factory()
    record = RemediationReassessment(
        case_id=case_id,
        planned_assessment_id="id-cas-idempotent",
        selected_action_ids=[action_id],
        included_requirement_ids=["A.9.2"],
        excluded_holdout_ids=[],
        status="PENDING",
    )
    db.add(record)
    db.commit()
    record_id = record.id
    db.close()

    # first finalizer wins
    db = client.session_factory()
    reassessment_module._finalize(db, org_id, case_id, record_id, "LAUNCHED", None, None)
    db.close()

    # stale second finalizer: the guard makes it a no-op
    db = client.session_factory()
    reassessment_module._finalize(
        db, org_id, case_id, record_id, "LAUNCH_FAILED", "stale", None
    )
    db.close()

    detail = client.get(_url(org_id, case_id)).json()
    launched = [
        e for e in detail["events"] if e["event_type"] == "reassessment_launched"
    ]
    assert len(launched) == 1  # no duplicate audit event

    db = client.session_factory()
    rec = db.get(RemediationReassessment, record_id)
    assert rec.status == "LAUNCHED"  # terminal state not rewritten
    assert rec.error is None
    db.close()


def test_runner_launch_false_treated_as_launched(client, plan_case, monkeypatch):
    org_id, case_id, action_id = plan_case
    _to_done(client, org_id, case_id, action_id)
    monkeypatch.setattr(runner, "launch", lambda sf, aid: False)  # live local thread
    r = client.post(
        _url(org_id, case_id, "/reassessments"),
        json={"selected_action_ids": [action_id]},
    )
    assert r.status_code == 202 and r.json()["status"] == "LAUNCHED"


# ---------------------------------------------- 0018 remediation operations


def test_in_progress_requires_due_date(client, plan_case):
    """Launch gate: an APPROVED action without a human-set deadline cannot
    move to IN_PROGRESS (422 naming the missing field); setting the deadline
    through a re-review unlocks the transition."""
    org_id, case_id, action_id = plan_case
    r = client.post(
        _url(org_id, case_id, f"/actions/{action_id}/review"),
        json={"action": "approve", "priority": "haute"},  # deliberately no due_date
    )
    assert r.status_code == 200
    assert r.json()["due_date"] is None  # nothing invented
    r = _lifecycle(client, org_id, case_id, action_id, "IN_PROGRESS")
    assert r.status_code == 422
    assert "échéance" in r.json()["detail"]
    # re-review with a deadline (human decision) unlocks the launch
    r = _review(client, org_id, case_id, action_id, action="approve", priority="haute")
    assert r.status_code == 200
    assert r.json()["due_date"] == "2026-09-30"
    assert _lifecycle(client, org_id, case_id, action_id, "IN_PROGRESS").status_code == 200


def test_case_planning_update_optimistic_revision(client, plan_case):
    """Owner/deadline/closure criterion are human fields under an optimistic
    revision check: a stale expected_revision is a 409, a valid one bumps the
    revision and appends a case_planning_updated event."""
    org_id, case_id, _ = plan_case
    case = client.get(_url(org_id, case_id, "")).json()
    assert case["owner_role"] is None and case["planning_revision"] == 0

    r = client.put(
        _url(org_id, case_id, "/planning"),
        json={
            "expected_revision": 0,
            "owner_role": "Responsable conformité",
            "due_date": "2026-10-15",
            "closure_criterion": "Écart refermé par une réévaluation conforme.",
            "editor_label": "Yassine",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["owner_role"] == "Responsable conformité"
    assert body["due_date"] == "2026-10-15"
    assert body["planning_revision"] == 1
    assert body["planning_editor_label"] == "Yassine"
    assert any(e["event_type"] == "case_planning_updated" for e in body["events"])

    # stale revision: no silent overwrite
    r = client.put(
        _url(org_id, case_id, "/planning"),
        json={"expected_revision": 0, "owner_role": "Autre"},
    )
    assert r.status_code == 409
    assert client.get(_url(org_id, case_id, "")).json()["owner_role"] == (
        "Responsable conformité"
    )

    # explicit clearing is a decision, audited like any other
    r = client.put(
        _url(org_id, case_id, "/planning"),
        json={"expected_revision": 1},
    )
    assert r.status_code == 200
    assert r.json()["owner_role"] is None
    assert r.json()["planning_revision"] == 2


def test_workflow_summary_in_case_payloads(client, plan_case):
    """List/detail payloads carry the compact workflow summary: plan status,
    action counts, next-action key and the closure RECOMMENDATION."""
    org_id, case_id, action_id = plan_case
    wf = client.get(_url(org_id, case_id, "")).json()["workflow"]
    assert wf["active_plan_status"] == "VERIFIED"
    assert wf["blocker_reason"] is None
    assert wf["pending_action_count"] == 1
    assert wf["next_action_key"] == "review_actions"
    assert wf["closure"]["recommended_ready"] is False
    assert "open_actions" in wf["closure"]["recommendations"]

    # drive the action to DONE with a recorded effectiveness -> close_case
    _to_done(client, org_id, case_id, action_id)
    client.post(
        _url(org_id, case_id, f"/actions/{action_id}/effectiveness"),
        json={"effectiveness": "EFFECTIVE", "note": "Réévaluation favorable."},
    )
    listed = client.get(f"/api/organizations/{org_id}/remediation-cases").json()
    wf = next(c for c in listed if c["id"] == case_id)["workflow"]
    assert wf["pending_action_count"] == 0
    assert wf["open_action_count"] == 0
    assert wf["next_action_key"] == "close_case"
    assert wf["closure"]["recommended_ready"] is True

"""Planner tests (M7a core): requirement binding, source-bound exact-only
quote binding, abstention taxonomy, activation/supersession, PLANNING lease
(stale recovery, lost heartbeat), operational aborts."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import (
    RemediationAttempt,
    RemediationCase,
    RemediationPlan,
)
from app.pipeline import llm as llm_service
from app.pipeline.llm import CALL_SUCCESS, LLMCall, LLMOutcome
from app.remediation import planner as planner_module
from app.remediation.service import RemediationConflictError
from tests.test_pipeline import FUZZY_QUOTE, QUOTE, FakeLLM
from tests.test_remediation_cases import (  # noqa: F401 — shared fixtures
    _create_case,
    _triage_json,
    _url,
    client,
    gap_env,
)


def _plan_json(impacted=("A.9.2",), quote=None, source=None) -> str:
    return json.dumps(
        {
            "gap_restatement": "La preuve de signalement d'incident est partielle.",
            "root_cause_hypotheses": [
                {"label": "H1", "hypothesis": "Processus de preuve non défini."}
            ],
            "actions": [
                {
                    "action_type": "document_amendment",
                    "description": "Compléter la politique d'incident.",
                    "rationale": "Couvrir entièrement l'exigence.",
                    "owner_role": "Responsable conformité",
                    "success_criterion": "La politique décrit le signalement sous 48 h.",
                    "impacted_requirement_ids": list(impacted),
                    "policy_quote": quote,
                    "quote_source_id": source,
                }
            ],
        },
        ensure_ascii=False,
    )


class DynamicFake:
    """Scripted provider whose entries may be callables(messages) -> content,
    letting tests bind quotes to the real server-assigned source ids that
    only appear in the prompt."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.requests = []
        self.heartbeats = 0

    def complete_json(self, messages, *, json_schema=None, schema_name="x", on_call_finished=None):
        self.requests.append(messages)
        if on_call_finished is not None:
            self.heartbeats += 1
            on_call_finished()
        entry = self.scripts.pop(0)
        content = entry(messages) if callable(entry) else entry
        now = "2026-07-10T00:00:00+00:00"
        if content is None:
            call = LLMCall(
                provider="mistral", requested_model="fake", status="HTTP_ERROR",
                request_messages=messages, response_format={}, temperature=0.0,
                http_status=500, error="boom", started_at=now, finished_at=now,
            )
            return LLMOutcome(content=None, calls=[call], error="échec")
        call = LLMCall(
            provider="fake", requested_model="fake-model", status=CALL_SUCCESS,
            request_messages=messages, response_format={}, temperature=0.0,
            reported_model="fake-model-v1", raw_response=content,
            started_at=now, finished_at=now,
        )
        return LLMOutcome(content=content, calls=[call])


def _source_ids(messages) -> list[str]:
    """Server-assigned policy source ids, parsed from the prompt's evidence
    block (the only place the model could learn them from)."""
    text = "\n".join(m["content"] for m in messages)  # repair keeps the base prompt
    return [
        line.split('"source_id": "')[1].split('"')[0]
        for line in text.splitlines()
        if '"source_id": "' in line
    ]


@pytest.fixture()
def approved_case(client, gap_env):
    """A case on A.9.2 with human-approved triage (scope local)."""
    org_id, aid, by_req = gap_env
    body = _create_case(client, org_id, by_req["A.9.2"]).json()
    case_id, draft_id = body["id"], body["triage_drafts"][0]["id"]
    r = client.post(
        _url(org_id, case_id, "/triage/approve"), json={"triage_draft_id": draft_id}
    )
    assert r.status_code == 200 and r.json()["status"] == "TRIAGE_APPROVED"
    return org_id, case_id


def _post_plan(client, org_id, case_id):
    return client.post(_url(org_id, case_id, "/plans"), json={})


# --------------------------------------------------------------- happy path


def test_verified_plan_with_bound_exact_quote(client, approved_case):
    org_id, case_id = approved_case
    fake = DynamicFake(
        [lambda m: _plan_json(quote=QUOTE, source=_source_ids(m)[0])]
    )
    llm_service.set_provider(fake)
    r = _post_plan(client, org_id, case_id)
    assert r.status_code == 200
    plan = r.json()
    assert plan["status"] == "VERIFIED"
    assert plan["allowed_requirement_ids"] == ["A.9.2"]
    assert plan["input_kb"]["A.9.2"]["requirement_fr"]
    assert plan["input_triage_snapshot"]["classification"] == "evidence_gap"
    (action,) = plan["actions"]
    assert action["policy_quote"] == QUOTE
    assert action["match_method"] == "exact"
    assert action["matched_chunk_id"]  # bound to the claimed source
    assert action["lifecycle"] == "PROPOSED" and action["review_status"] == "PENDING"
    # case activated the plan and returned to PLAN_READY with the lease cleared
    detail = client.get(_url(org_id, case_id)).json()
    assert detail["status"] == "PLAN_READY"
    assert detail["active_plan_id"] == plan["id"]
    assert fake.heartbeats >= 1  # lease renewed via on_call_finished


def test_plan_forbidden_outside_triage_approved_or_plan_ready(client, gap_env):
    org_id, _aid, by_req = gap_env
    case_id = _create_case(client, org_id, by_req["A.9.2"]).json()["id"]
    assert _post_plan(client, org_id, case_id).status_code == 409  # TRIAGE


# ------------------------------------------------------- deterministic gates


def test_valid_but_unoffered_requirement_id_rejected(client, approved_case):
    """A.4.5 exists in the KB but was never offered (scope local, only A.9.2
    is allowed): the KB analogue of a quote from the wrong passage."""
    org_id, case_id = approved_case
    llm_service.set_provider(
        DynamicFake([_plan_json(impacted=("A.4.5",)), _plan_json(impacted=("A.4.5",))])
    )
    r = _post_plan(client, org_id, case_id)
    assert r.status_code == 200
    plan = r.json()
    assert plan["status"] == "ABSTAINED"
    assert plan["abstain_reason"] == "verification_failed"
    assert plan["draft_attempts"] == 2  # one repair retry happened
    assert plan["actions"] == []  # no actions persisted from a rejected plan


def test_quote_from_wrong_source_rejected(client, approved_case):
    """The quote EXISTS in the evidence, but quote_source_id names a different
    passage: binding must fail (never scan the whole evidence list)."""
    org_id, case_id = approved_case

    def wrong_source(m):
        ids = _source_ids(m)
        others = [i for i in ids if QUOTE not in _evidence_text(m, i)]
        return _plan_json(quote=QUOTE, source=others[0] if others else "chunk-inexistant")

    def _evidence_text(messages, source_id):
        # crude but deterministic: locate the JSON entry for this source id
        # anywhere in the conversation (repair appends to the base prompt)
        text = "\n".join(m["content"] for m in messages)
        for block in text.split('"source_id"'):
            if block.startswith(f': "{source_id}"'):
                return block
        return ""

    llm_service.set_provider(DynamicFake([wrong_source, wrong_source]))
    r = _post_plan(client, org_id, case_id)
    plan = r.json()
    assert plan["status"] == "ABSTAINED"
    assert plan["abstain_reason"] == "verification_failed"


def test_fabricated_and_fuzzy_quotes_rejected(client, approved_case):
    org_id, case_id = approved_case
    fabricated = lambda m: _plan_json(  # noqa: E731
        quote="Cette phrase n'existe dans aucun document.", source=_source_ids(m)[0]
    )
    llm_service.set_provider(DynamicFake([fabricated, fabricated]))
    plan = _post_plan(client, org_id, case_id).json()
    assert plan["status"] == "ABSTAINED"
    assert plan["abstain_reason"] == "verification_failed"

    # fuzzy near-match (accepted by the read-side verifier as a candidate)
    # is NOT acceptable for plan verification: exact-only
    def fuzzy(m):
        ids = [i for i in _source_ids(m) if True]
        return _plan_json(quote=FUZZY_QUOTE, source=ids[0])

    llm_service.set_provider(DynamicFake([fuzzy, fuzzy]))
    plan = _post_plan(client, org_id, case_id).json()
    assert plan["status"] == "ABSTAINED"
    assert plan["abstain_reason"] == "verification_failed"


def test_malformed_json_twice_abstains_schema_invalid(client, approved_case):
    org_id, case_id = approved_case
    llm_service.set_provider(DynamicFake(["pas du json", "toujours pas"]))
    plan = _post_plan(client, org_id, case_id).json()
    assert plan["status"] == "ABSTAINED"
    assert plan["abstain_reason"] == "schema_invalid"
    # attempts + calls persisted for audit
    db = client.session_factory()
    attempts = db.scalars(
        select(RemediationAttempt).where(RemediationAttempt.plan_id == plan["id"])
    ).all()
    assert [a.attempt_number for a in attempts] == [1, 2]
    assert all(not a.parsed_ok for a in attempts)
    db.close()


def test_provider_failure_abstains_llm_error(client, approved_case):
    org_id, case_id = approved_case
    llm_service.set_provider(DynamicFake([None]))
    plan = _post_plan(client, org_id, case_id).json()
    assert plan["status"] == "ABSTAINED" and plan["abstain_reason"] == "llm_error"
    # first plan of the case: a completed ABSTAINED outcome still activates
    detail = client.get(_url(org_id, case_id)).json()
    assert detail["active_plan_id"] == plan["id"]
    assert detail["status"] == "PLAN_READY"


# ------------------------------------------------ activation / supersession


def test_verified_replacement_supersedes_and_abstained_does_not(client, approved_case):
    org_id, case_id = approved_case
    # plan 1: VERIFIED
    llm_service.set_provider(DynamicFake([_plan_json()]))
    p1 = _post_plan(client, org_id, case_id).json()
    assert p1["status"] == "VERIFIED"
    # plan 2: ABSTAINED — the VERIFIED plan must stay active
    llm_service.set_provider(DynamicFake(["x", "y"]))
    p2 = _post_plan(client, org_id, case_id).json()
    assert p2["status"] == "ABSTAINED"
    detail = client.get(_url(org_id, case_id)).json()
    assert detail["active_plan_id"] == p1["id"]
    statuses = {p["id"]: p["status"] for p in detail["plans"]}
    assert statuses[p1["id"]] == "VERIFIED"  # untouched
    # plan 3: VERIFIED — supersedes plan 1 atomically
    llm_service.set_provider(DynamicFake([_plan_json()]))
    p3 = _post_plan(client, org_id, case_id).json()
    detail = client.get(_url(org_id, case_id)).json()
    assert detail["active_plan_id"] == p3["id"]
    p1_row = next(p for p in detail["plans"] if p["id"] == p1["id"])
    assert p1_row["status"] == "SUPERSEDED"
    assert p1_row["superseded_by_plan_id"] == p3["id"]


def test_abstained_active_plan_superseded_by_next_completed_outcome(client, approved_case):
    org_id, case_id = approved_case
    llm_service.set_provider(DynamicFake(["x", "y"]))  # ABSTAINED, activates (first)
    p1 = _post_plan(client, org_id, case_id).json()
    llm_service.set_provider(DynamicFake(["x", "y"]))  # ABSTAINED again
    p2 = _post_plan(client, org_id, case_id).json()
    detail = client.get(_url(org_id, case_id)).json()
    assert detail["active_plan_id"] == p2["id"]
    p1_row = next(p for p in detail["plans"] if p["id"] == p1["id"])
    assert p1_row["status"] == "SUPERSEDED"


# --------------------------------------------------- operational aborts


def test_retrieval_failure_persists_abstained_row_and_restores_state(
    client, approved_case, monkeypatch
):
    org_id, case_id = approved_case

    def boom(*a, **kw):
        raise ConnectionError("qdrant down")

    monkeypatch.setattr(planner_module, "hybrid_search", boom)
    r = _post_plan(client, org_id, case_id)
    assert r.status_code == 200  # explicit ABSTAINED row, never an ambiguous 5xx
    plan = r.json()
    assert plan["status"] == "ABSTAINED" and plan["abstain_reason"] == "retrieval_error"
    detail = client.get(_url(org_id, case_id)).json()
    # operational abort: NEVER activated; no plan was active -> TRIAGE_APPROVED
    assert detail["active_plan_id"] is None
    assert detail["status"] == "TRIAGE_APPROVED"

    # with an active VERIFIED plan, the abort restores it and PLAN_READY
    monkeypatch.undo()
    llm_service.set_provider(DynamicFake([_plan_json()]))
    p1 = _post_plan(client, org_id, case_id).json()
    monkeypatch.setattr(planner_module, "hybrid_search", boom)
    _post_plan(client, org_id, case_id)
    detail = client.get(_url(org_id, case_id)).json()
    assert detail["active_plan_id"] == p1["id"] and detail["status"] == "PLAN_READY"


def test_stale_planning_lease_recovered_then_fresh_draft(client, approved_case):
    org_id, case_id = approved_case
    # simulate a crashed draft: PLANNING with an expired heartbeat
    db = client.session_factory()
    case = db.get(RemediationCase, case_id)
    case.status = "PLANNING"
    case.planning_token = "tok-crashed"
    case.planning_started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    case.planning_heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    db.close()

    llm_service.set_provider(DynamicFake([_plan_json()]))
    r = _post_plan(client, org_id, case_id)
    assert r.status_code == 200
    plan = r.json()
    assert plan["status"] == "VERIFIED"
    detail = client.get(_url(org_id, case_id)).json()
    # the recovery row exists as an audit record, never activated
    recovered = [p for p in detail["plans"] if p["abstain_reason"] == "draft_interrupted"]
    assert len(recovered) == 1 and recovered[0]["status"] == "ABSTAINED"
    assert detail["active_plan_id"] == plan["id"]
    events = [e["event_type"] for e in detail["events"]]
    assert "plan_draft_recovered" in events


def test_fresh_planning_lease_blocks_concurrent_draft(client, approved_case):
    org_id, case_id = approved_case
    db = client.session_factory()
    case = db.get(RemediationCase, case_id)
    case.status = "PLANNING"
    case.planning_token = "tok-live"
    case.planning_started_at = datetime.now(timezone.utc)
    case.planning_heartbeat_at = datetime.now(timezone.utc)
    db.commit()
    db.close()
    llm_service.set_provider(DynamicFake([_plan_json()]))
    assert _post_plan(client, org_id, case_id).status_code == 409


def test_lost_heartbeat_refuses_persistence(client, approved_case):
    org_id, case_id = approved_case

    class BrokenFactory:
        """Heartbeat sessions whose writes fail: the lease is marked lost."""

        def __call__(self):
            raise RuntimeError("db unreachable for heartbeats")

    llm_service.set_provider(DynamicFake([_plan_json()]))
    db = client.session_factory()
    with pytest.raises(RemediationConflictError):
        planner_module.draft_plan(db, BrokenFactory(), org_id, case_id)
    plans = db.scalars(
        select(RemediationPlan).where(RemediationPlan.case_id == case_id)
    ).all()
    assert plans == []  # nothing persisted from the lost-lease draft
    db.close()

"""M8 Node ⑤ reporting: scope contract, conformity, risk register, trust panel."""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import reporting as reporting_api
from app.db import Base, get_db
from app.main import app
from app.models import (
    Assessment,
    AssessmentAttempt,
    ChatMessage,
    Conversation,
    Finding,
    FindingReview,
    Organization,
    RemediationAction,
    RemediationCase,
    RemediationCaseFinding,
    RemediationPlan,
)
from app.services import scoring
from app.services import scoring_policy as sp

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    db = TestSession()
    yield db
    db.close()


@pytest.fixture()
def client(db_session):
    def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[reporting_api.get_reporting_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _org(db, name="Lumen AI") -> str:
    org = Organization(name=name)
    db.add(org)
    db.commit()
    return org.id


def _assessment(db, org_id, *, status="COMPLETED", requirement_ids=None, corpus="1.3.0") -> str:
    a = Assessment(
        organization_id=org_id,
        corpus_version=corpus,
        status=status,
        requirement_ids=requirement_ids,
    )
    db.add(a)
    db.commit()
    return a.id


def _finding(
    db,
    assessment_id,
    rid,
    *,
    ai_status="VERIFIED",
    verdict=None,
    human_verdict=None,
    review_action="approve",
    reviewed_at=NOW,
    abstain_reason=None,
    domain=None,
    requirement_fr=None,
) -> str:
    confirmed = human_verdict is not None
    f = Finding(
        assessment_id=assessment_id,
        requirement_id=rid,
        status=ai_status,
        verdict=verdict,
        abstain_reason=abstain_reason,
        attempts=1,
        domain=domain,
        requirement_fr=requirement_fr,
        review_status="CONFIRMED" if confirmed else "PENDING",
        review_action=review_action if confirmed else None,
        human_verdict=human_verdict,
        reviewed_at=reviewed_at if confirmed else None,
        review_count=1 if confirmed else 0,
    )
    db.add(f)
    db.commit()
    return f.id


def _scope(db, org_id, **kw):
    return scoring.build_reporting_scope(db, org_id, **kw)


# ---------------------------------------------------------------- scope contract


def test_denominator_is_scored_only_with_coverage(db_session):
    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["4.1", "4.2", "4.3", "4.4"])
    _finding(db_session, a, "4.1", human_verdict="compliant")
    _finding(db_session, a, "4.2", human_verdict="partial")
    _finding(db_session, a, "4.3")  # PENDING -> coverage gap
    # 4.4: no finding at all -> coverage gap
    out = scoring.conformity_summary(_scope(db_session, org, assessment_id=a))
    assert out["scored"] == 2
    assert out["total_in_scope"] == 4
    assert out["coverage_pct"] == 50.0
    assert out["global_pct"] == 75.0  # (1 + 0.5) / 2
    dom = out["domains"][0]
    assert dom["domain"] == "4"
    assert dom["pending_review"] == 1 and dom["not_assessed"] == 1


def test_overridden_ai_abstained_finding_is_scored(db_session):
    """status=ABSTAINED + review override is the designed resolution path —
    Node ⑤ must score the human verdict, not discard it."""
    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["A.7.4"])
    _finding(
        db_session, a, "A.7.4",
        ai_status="ABSTAINED", abstain_reason="fuzzy_citation",
        human_verdict="non_compliant", review_action="override",
    )
    out = scoring.conformity_summary(_scope(db_session, org, assessment_id=a))
    assert out["scored"] == 1 and out["global_pct"] == 0.0
    register = scoring.risk_register(_scope(db_session, org, assessment_id=a))
    assert len(register["rows"]) == 1
    assert register["rows"][0]["severity"] == "high"  # gap 2 x weight 3


def test_org_scope_universe_and_disclosures(db_session):
    org = _org(db_session)
    done1 = _assessment(db_session, org, requirement_ids=["4.1", "4.2"])
    done2 = _assessment(db_session, org, requirement_ids=["4.2", "5.1"])
    running = _assessment(db_session, org, status="RUNNING", requirement_ids=["9.1"])
    legacy = _assessment(db_session, org, requirement_ids=None)  # pre-0011
    scope = _scope(db_session, org)
    assert scope.requirement_universe == ["4.1", "4.2", "5.1"]
    assert set(scope.included_assessment_ids) == {done1, done2}
    assert scope.excluded_preliminary_assessment_ids == [running]
    assert scope.legacy_manifest_missing_ids == [legacy]
    assert scope.scope_complete is False
    assert scope.is_preliminary is False
    assert scope.is_official is False  # blocked by legacy manifest
    assert "legacy_manifest_missing" in scope.official_blockers


def test_include_preliminary_marks_whole_result(db_session):
    org = _org(db_session)
    _assessment(db_session, org, requirement_ids=["4.1"])
    running = _assessment(db_session, org, status="RUNNING", requirement_ids=["9.1"])
    scope = _scope(db_session, org, include_preliminary=True)
    assert running in scope.included_assessment_ids
    assert "9.1" in scope.requirement_universe
    assert scope.is_preliminary is True and scope.is_official is False


def test_assessment_mode_not_completed_is_preliminary(db_session):
    org = _org(db_session)
    a = _assessment(db_session, org, status="RUNNING", requirement_ids=["4.1"])
    scope = _scope(db_session, org, assessment_id=a)
    assert scope.is_preliminary is True
    assert "assessment_not_completed" in scope.official_blockers
    done = _assessment(db_session, org, requirement_ids=["4.1"])
    scope = _scope(db_session, org, assessment_id=done)
    assert scope.is_official is True


def test_latest_confirmed_wins_across_assessments(db_session):
    org = _org(db_session)
    a1 = _assessment(db_session, org, requirement_ids=["4.1"])
    a2 = _assessment(db_session, org, requirement_ids=["4.1"])
    _finding(db_session, a1, "4.1", human_verdict="non_compliant", reviewed_at=NOW)
    _finding(
        db_session, a2, "4.1", human_verdict="compliant",
        reviewed_at=NOW + timedelta(hours=1),
    )
    out = scoring.conformity_summary(_scope(db_session, org))
    assert out["global_pct"] == 100.0  # the newer review wins


# ---------------------------------------------------------------- risk register


def test_register_rows_only_for_confirmed_gaps(db_session):
    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["4.1", "4.2", "4.3", "6.3"])
    _finding(db_session, a, "4.1", human_verdict="compliant")     # no row
    _finding(db_session, a, "4.2", human_verdict="partial")       # row
    _finding(db_session, a, "4.3")                                # PENDING: no row
    _finding(db_session, a, "6.3", human_verdict="missing")       # row
    out = scoring.risk_register(_scope(db_session, org, assessment_id=a))
    by_rid = {r["requirement_id"]: r for r in out["rows"]}
    assert set(by_rid) == {"4.2", "6.3"}
    # 4.2: gap 1 x weight 2 = 2 low; 6.3: gap 3 x weight 1 = 3 medium
    assert (by_rid["4.2"]["severity_score"], by_rid["4.2"]["severity"]) == (2, "low")
    assert (by_rid["6.3"]["severity_score"], by_rid["6.3"]["severity"]) == (3, "medium")
    assert by_rid["4.2"]["weight_source"] == "policy"
    assert "exigence 4.2" in by_rid["4.2"]["risk_statement_fr"]
    assert out["counts"] == {"high": 0, "medium": 1, "low": 1, "unscored": 0}
    # medium sorts before low
    assert [r["requirement_id"] for r in out["rows"]] == ["6.3", "4.2"]


def test_register_never_serves_live_kb_text(db_session):
    """Holdout posture: requirement text comes only from finding snapshots."""
    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["A.5.5"])  # holdout id
    _finding(db_session, a, "A.5.5", human_verdict="partial", requirement_fr=None)
    out = scoring.risk_register(_scope(db_session, org, assessment_id=a))
    assert out["rows"][0]["requirement_fr"] is None  # never filled from live KB
    assert out["rows"][0]["weight"] == 2  # weights/aggregates are fine


def test_unscored_weight_is_explicit(monkeypatch, db_session):
    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["4.1"])
    _finding(db_session, a, "4.1", human_verdict="partial")
    empty = {"m8-1": {"authored_for_corpus_version": "1.3.0", "weights": {}}}
    monkeypatch.setattr(sp, "SCORING_POLICIES", empty)
    out = scoring.risk_register(_scope(db_session, org, assessment_id=a))
    row = out["rows"][0]
    assert row["weight"] is None and row["weight_source"] == "unscored_weight"
    assert row["severity"] is None and row["severity_score"] is None
    assert out["counts"]["unscored"] == 1


def test_policy_pinning_survives_current_policy_flip(monkeypatch, db_session):
    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["A.7.4"])
    _finding(db_session, a, "A.7.4", human_verdict="missing")
    baseline = scoring.risk_register(
        _scope(db_session, org, assessment_id=a, scoring_policy_version="m8-1")
    )["rows"]
    # a future policy downgrades every weight to 1 and becomes the default
    monkeypatch.setattr(
        sp,
        "SCORING_POLICIES",
        {
            "m8-1": sp.SCORING_POLICIES["m8-1"],
            "m8-2": {
                "authored_for_corpus_version": "1.4.0",
                "weights": {k: 1 for k in sp.SCORING_POLICIES["m8-1"]["weights"]},
            },
        },
    )
    monkeypatch.setattr(sp, "CURRENT_SCORING_POLICY", "m8-2")
    default_rows = scoring.risk_register(_scope(db_session, org, assessment_id=a))["rows"]
    pinned_rows = scoring.risk_register(
        _scope(db_session, org, assessment_id=a, scoring_policy_version="m8-1")
    )["rows"]
    assert default_rows[0]["severity"] == "medium"  # 3 x 1 under m8-2
    strip = lambda rows: [  # noqa: E731 — generated_at differs by design
        {k: v for k, v in r.items() if k != "scope"} for r in rows
    ]
    assert strip(pinned_rows) == strip(baseline)  # m8-1 reproduced exactly


def test_unknown_policy_version_is_422_listing_known(client, db_session):
    org = _org(db_session)
    r = client.get(
        f"/api/organizations/{org}/reporting/conformity",
        params={"scoring_policy_version": "m9-99"},
    )
    assert r.status_code == 422 and "m8-1" in r.json()["detail"]


def test_unknown_org_and_assessment_are_404(client, db_session):
    assert client.get("/api/organizations/nope/reporting/conformity").status_code == 404
    org = _org(db_session)
    r = client.get(
        f"/api/organizations/{org}/reporting/conformity",
        params={"assessment_id": "nope"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------- treatment


def _case_with_plans(db, org_id, finding_id, rid):
    case = RemediationCase(organization_id=org_id, title="Cas", status="TRIAGE")
    db.add(case)
    db.flush()
    db.add(
        RemediationCaseFinding(
            case_id=case.id,
            finding_id=finding_id,
            is_primary=True,
            link_source="creation",
            finding_review_count=1,
            finding_human_verdict="non_compliant",
            finding_requirement_id=rid,
        )
    )
    superseded = RemediationPlan(
        case_id=case.id, sequence=1, status="SUPERSEDED",
        superseded_at=NOW, prompt_version="p1", corpus_version="1.3.0",
    )
    active = RemediationPlan(
        case_id=case.id, sequence=2, status="VERIFIED",
        gap_restatement="g", root_cause_hypotheses=[], raw_draft="{}",
        prompt_version="p1", corpus_version="1.3.0",
    )
    db.add_all([superseded, active])
    db.flush()

    def _approved(plan_id, position):
        return RemediationAction(
            plan_id=plan_id, position=position, action_type="process_change",
            ai_description="d", ai_rationale="r", ai_owner_role="o",
            ai_success_criterion="s", review_status="CONFIRMED",
            review_action="approve", description="d", rationale="r",
            owner_role="o", success_criterion="s", priority="haute",
            reviewed_at=NOW, lifecycle="APPROVED",
        )

    db.add_all([
        _approved(superseded.id, 1), _approved(superseded.id, 2),  # inert history
        _approved(active.id, 1),
    ])
    case.active_plan_id = active.id
    db.commit()
    return case.id


def test_treatment_counts_only_active_plan_actions(db_session):
    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["10.2"])
    fid = _finding(db_session, a, "10.2", human_verdict="non_compliant")
    case_id = _case_with_plans(db_session, org, fid, "10.2")
    out = scoring.risk_register(_scope(db_session, org, assessment_id=a))
    treatment = out["rows"][0]["treatment"]
    assert treatment["active_case_id"] == case_id
    assert treatment["approved_action_count"] == 1  # superseded plan's 2 ignored
    assert treatment["closed_case_ids"] == []


# ---------------------------------------------------------------- suggested priority


def test_suggested_priority_from_link_snapshots():
    links = [("10.2", "non_compliant"), ("7.3", "partial")]
    # 10.2: 2x3=6 high; 7.3: 1x1=1 low -> max wins
    out = scoring.suggested_priority_for_action(["10.2", "7.3"], links)
    assert out["suggested_priority"] == "haute"
    assert out["suggested_priority_policy_version"] == "m8-1"
    out = scoring.suggested_priority_for_action(["7.3"], links)
    assert out["suggested_priority"] == "basse"


def test_suggested_priority_null_reasons(monkeypatch):
    links = [("10.2", "non_compliant")]
    out = scoring.suggested_priority_for_action(["4.1"], links)  # scope mismatch
    assert out["suggested_priority"] is None
    assert out["suggested_priority_reason"] == "no_linked_gap_in_action_scope"
    monkeypatch.setattr(
        sp, "SCORING_POLICIES",
        {"m8-1": {"authored_for_corpus_version": "1.3.0", "weights": {}}},
    )
    out = scoring.suggested_priority_for_action(["10.2"], links)
    assert out["suggested_priority"] is None
    assert out["suggested_priority_reason"] == "all_matching_weights_unscored"


# ---------------------------------------------------------------- trust panel


def test_trust_panel_typed_gate_and_review_events(client, db_session):
    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["4.1", "4.2"])

    def _attempt(rid, n, outcome, codes):
        db_session.add(
            AssessmentAttempt(
                assessment_id=a, requirement_id=rid, attempt_number=n,
                prompt_version="p1", parsed_ok=outcome == "parsed",
                attempt_outcome=outcome, verifier_error_codes=codes,
            )
        )

    _attempt("4.1", 1, "parsed", ["citation_not_found"])
    _attempt("4.1", 2, "parsed", [])
    _attempt("4.2", 1, "schema_invalid", [])
    _attempt("4.2", 2, "provider_failure", [])
    # legacy row: outcome unclassified, codes unavailable
    db_session.add(
        AssessmentAttempt(
            assessment_id=a, requirement_id="4.2", attempt_number=3,
            prompt_version="p0", parsed_ok=False,
            attempt_outcome="legacy_unclassified", verifier_error_codes=None,
        )
    )
    fid = _finding(db_session, a, "4.1", human_verdict="compliant")
    _finding(
        db_session, a, "4.2", ai_status="ABSTAINED",
        abstain_reason="verification_failed",
        human_verdict="non_compliant", review_action="override",
    )
    # immutable review events incl. a re-review (approve then override)
    db_session.add_all([
        FindingReview(finding_id=fid, sequence=1, action="approve", human_verdict="compliant"),
        FindingReview(finding_id=fid, sequence=2, action="override", human_verdict="partial"),
    ])
    conv = Conversation(organization_id=org, title="t")
    db_session.add(conv)
    db_session.flush()
    db_session.add(
        ChatMessage(
            conversation_id=conv.id, question="q",
            answer="a", status="ANSWERED", evidence_scope="policy",
            stripped_citations=[{"id": "c1"}, {"id": "c2"}],
            draft_attempts=1, prompt_version="p1", corpus_version="1.3.0",
        )
    )
    db_session.commit()

    r = client.get(f"/api/organizations/{org}/reporting/trust")
    assert r.status_code == 200
    body = r.json()
    gate = body["gate"]
    assert gate["drafts_total"] == 5
    assert gate["drafts_parsed"] == 2
    assert gate["drafts_schema_invalid"] == 1
    assert gate["drafts_provider_failure"] == 1
    assert gate["legacy_unclassified"] == 1
    assert gate["drafts_with_unsupported_citation"] == 1
    assert gate["unsupported_draft_rate_pct"] == 25.0  # 1 / 4 classified-with-codes
    assert gate["verifier_error_code_counts"] == {"citation_not_found": 1}
    assert gate["findings_abstained_by_verifier"] == 1
    assert gate["unsupported_citations_displayed"] == 0
    review = body["review"]
    assert review["review_events"] == 2
    assert review["intervention_rate_pct"] == 50.0
    assert review["verdict_override_rate_pct"] == 50.0
    chat = body["chat"]
    assert chat["metric_scope"] == "organization"
    assert chat["stripped_citation_count"] == 2


def test_trust_panel_zero_denominators(client, db_session):
    org = _org(db_session)
    r = client.get(f"/api/organizations/{org}/reporting/trust")
    body = r.json()
    assert body["gate"]["drafts_total"] == 0
    assert body["gate"]["unsupported_draft_rate_pct"] is None
    assert body["review"]["intervention_rate_pct"] is None


def test_m6_benchmark_is_checksum_bound_to_artifact():
    artifact = REPO_ROOT / scoring.M6_BENCHMARK["source_artifact"]
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert digest == scoring.M6_BENCHMARK["source_artifact_sha256"], (
        "eval/m6/rapport_m6.md changed: re-verify the benchmark constants "
        "against the artifact, then update the pinned sha256"
    )


# ------------------------------------------------- review round (P1/P2 fixes)


def test_out_of_manifest_finding_never_scores(db_session):
    """P1 regression: a confirmed finding whose requirement is NOT in its own
    assessment's frozen manifest must be excluded — before the guard it
    inflated global_pct to 200% while the domain stayed at 100%."""
    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["4.1"])
    _finding(db_session, a, "4.1", human_verdict="compliant")
    _finding(db_session, a, "5.1", human_verdict="compliant")  # out-of-manifest
    out = scoring.conformity_summary(_scope(db_session, org, assessment_id=a))
    assert out["global_pct"] == 100.0
    assert out["scored"] == 1
    assert out["verdict_counts"]["compliant"] == 1
    assert [d["domain"] for d in out["domains"]] == ["4"]
    # org mode: same exclusion (5.1 is in no included manifest)
    out = scoring.conformity_summary(_scope(db_session, org))
    assert out["global_pct"] == 100.0 and out["scored"] == 1
    # and the rogue finding cannot smuggle a register row either
    register = scoring.risk_register(_scope(db_session, org))
    assert register["rows"] == []


def test_register_rows_carry_soa_applicability(db_session):
    """P2: a scored risk on a control declared non-applicable stays in the
    register (annotate, never filter) and DISCLOSES the declaration."""
    from app.services import soa as soa_service

    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["A.9.4", "A.9.2"])
    _finding(db_session, a, "A.9.4", human_verdict="partial")
    _finding(db_session, a, "A.9.2", human_verdict="missing")
    soa_service.record_decision(
        db_session, org, "A.9.4", applicable=False,
        justification_fr="Hors périmètre produit.",
    )
    out = scoring.risk_register(_scope(db_session, org, assessment_id=a))
    by_rid = {r["requirement_id"]: r for r in out["rows"]}
    assert set(by_rid) == {"A.9.4", "A.9.2"}  # never filtered
    assert by_rid["A.9.4"]["applicable"] is False
    assert by_rid["A.9.4"]["applicability_justification_fr"] == "Hors périmètre produit."
    assert by_rid["A.9.2"]["applicable"] is True
    assert by_rid["A.9.2"]["applicability_justification_fr"] is None


def test_scope_meta_exposes_universe_and_review_cutoff(db_session):
    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["4.2", "4.1"])
    meta = _scope(db_session, org, assessment_id=a).meta()
    assert meta["requirement_universe"] == ["4.2", "4.1"]  # the exact manifest
    assert meta["review_cutoff"] == meta["generated_at"]


def test_calculators_work_from_the_detached_scope_alone(db_session):
    """P2: trust_panel and soa_table take NO db handle — everything they
    render was materialized into the scope at build time."""
    from app.services import soa as soa_service

    org = _org(db_session)
    a = _assessment(db_session, org, requirement_ids=["A.9.2"])
    _finding(db_session, a, "A.9.2", human_verdict="compliant")
    scope = _scope(db_session, org, assessment_id=a)
    db_session.close()  # sever the session: calculators must not notice
    trust = scoring.trust_panel(scope)
    assert trust["review"]["review_events"] == 0
    soa = soa_service.soa_table(scope)
    assert len(soa["controls"]) == 38

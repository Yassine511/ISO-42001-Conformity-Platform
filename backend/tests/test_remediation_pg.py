"""PG-backed concurrency tests for the M7a remediation aggregate.

SQLite ignores SELECT ... FOR UPDATE: the case/finding row-lock invariants
(one active case per finding, event sequence monotonicity, PLANNING lease
exclusion, close-vs-mutation serialization) can only be validated against a
real Postgres. Skips when the dev service is unreachable
(`docker compose up -d postgres`).
"""

import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    Assessment,
    Document,
    DocumentPage,
    Finding,
    Organization,
    RemediationArtifact,
    RemediationCase,
    RemediationCaseFinding,
    RemediationEvent,
)
from app.pipeline import llm as llm_service
from app.remediation import actions as actions_module
from app.remediation import planner as planner_module
from app.remediation import service as service_module
from app.remediation.service import RemediationConflictError
from app.services.parsing import PARSER_VERSION
from tests.test_migrations import _connect, _postgres_available
from tests.test_remediation_planner import DynamicFake, _plan_json

pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason="dev Postgres (localhost:5433) unreachable — docker compose up -d postgres",
)


def _confirmed_finding(db, org_id: str, requirement_id: str = "A.9.2") -> str:
    assessment = Assessment(
        organization_id=org_id, corpus_version="1.2.0", status="COMPLETED"
    )
    db.add(assessment)
    db.flush()
    finding = Finding(
        assessment_id=assessment.id,
        requirement_id=requirement_id,
        status="VERIFIED",
        verdict="partial",
        rationale="Couverture partielle.",
        requirement_fr="Exigence de test.",
        domain="Test",
        review_status="CONFIRMED",
        review_action="approve",
        human_verdict="partial",
        reviewed_at=datetime.now(timezone.utc),
        review_count=1,
        attempts=1,
        retrieved=[],
    )
    db.add(finding)
    db.commit()
    return finding.id


@pytest.fixture()
def pg_env():
    name = f"remed_test_{uuid.uuid4().hex[:12]}"
    admin = _connect()
    admin.autocommit = True
    admin.execute(f'CREATE DATABASE "{name}"')
    admin.close()
    url = "postgresql+psycopg://int102:int102@localhost:5433/" + name
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    db = session_factory()
    org = Organization(name="Concurrence Remédiation SA")
    db.add(org)
    db.commit()
    from tests.conftest import seed_parsed_document

    seed_parsed_document(db, org.id, "politique.txt", ["Politique IA de test."], checksum="beef")
    from app.services.retrieval import index_organization

    index_organization(db, org.id)  # fake vector stack (conftest autouse)
    org_id = org.id
    finding_id = _confirmed_finding(db, org_id)
    db.close()

    yield session_factory, org_id, finding_id

    llm_service.set_provider(None)
    engine.dispose()
    admin = _connect()
    admin.autocommit = True
    admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.close()


def _approved_case(session_factory, org_id, finding_id) -> str:
    """Case with human-approved triage, ready for planning."""
    db = session_factory()
    case = service_module.create_case(db, org_id, finding_id)
    row = db.get(RemediationCase, case.id)
    row.classification = "evidence_gap"
    row.scope = "local"
    row.scope_rationale = "Écart isolé."
    row.triage_approved_at = datetime.now(timezone.utc)
    row.status = "TRIAGE_APPROVED"
    db.commit()
    case_id = case.id
    db.close()
    return case_id


def test_concurrent_case_creation_single_active_case(pg_env):
    """Two simultaneous creations from the same finding: the finding row lock
    serializes them and exactly one active case survives."""
    session_factory, org_id, finding_id = pg_env
    barrier = threading.Barrier(2, timeout=10)
    results: list = [None, None]

    def worker(slot: int) -> None:
        db = session_factory()
        try:
            barrier.wait()
            case = service_module.create_case(db, org_id, finding_id)
            results[slot] = ("ok", case.id)
        except RemediationConflictError as exc:
            results[slot] = ("conflict", str(exc))
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sorted(r[0] for r in results) == ["conflict", "ok"], results
    db = session_factory()
    active = db.scalars(
        select(RemediationCase)
        .join(RemediationCaseFinding, RemediationCaseFinding.case_id == RemediationCase.id)
        .where(
            RemediationCaseFinding.finding_id == finding_id,
            RemediationCase.status != "CLOSED",
        )
    ).all()
    db.close()
    assert len(active) == 1


def test_concurrent_reviews_serialize_with_monotonic_events(pg_env):
    """Two simultaneous reviews of the same action: the case lock serializes
    them (initial review, then re-review while APPROVED); event sequences
    stay strictly monotonic and review_count reaches 2."""
    session_factory, org_id, finding_id = pg_env
    case_id = _approved_case(session_factory, org_id, finding_id)
    llm_service.set_provider(DynamicFake([_plan_json()]))
    db = session_factory()
    plan = planner_module.draft_plan(db, session_factory, org_id, case_id)
    action_id = plan.actions[0].id
    db.close()

    barrier = threading.Barrier(2, timeout=10)
    outcomes: list = [None, None]

    def worker(slot: int, review_action: str, priority: str) -> None:
        db = session_factory()
        try:
            barrier.wait()
            actions_module.review_action(
                db, org_id, case_id, action_id,
                action=review_action, priority=priority,
            )
            outcomes[slot] = "ok"
        except RemediationConflictError:
            outcomes[slot] = "conflict"
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=(0, "approve", "haute")),
        threading.Thread(target=worker, args=(1, "edit", "basse")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert outcomes == ["ok", "ok"]  # second ran as a legal APPROVED re-review
    db = session_factory()
    from app.models import RemediationAction

    row = db.get(RemediationAction, action_id)
    assert row.review_count == 2 and row.lifecycle == "APPROVED"
    events = db.scalars(
        select(RemediationEvent)
        .where(RemediationEvent.case_id == case_id)
        .order_by(RemediationEvent.sequence)
    ).all()
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    db.close()


def test_concurrent_plan_drafts_excluded_by_lease(pg_env):
    """While one draft holds a fresh PLANNING lease, a second draft request
    is refused — never two interleaved drafts."""
    session_factory, org_id, finding_id = pg_env
    case_id = _approved_case(session_factory, org_id, finding_id)

    first_in_llm = threading.Event()
    release_first = threading.Event()
    outcomes: dict = {}

    class PausingFake(DynamicFake):
        def complete_json(self, messages, **kw):
            first_in_llm.set()
            assert release_first.wait(timeout=30)
            return super().complete_json(messages, **kw)

    llm_service.set_provider(PausingFake([_plan_json()]))

    def first() -> None:
        db = session_factory()
        try:
            plan = planner_module.draft_plan(db, session_factory, org_id, case_id)
            outcomes["first"] = plan.status
        finally:
            db.close()

    t1 = threading.Thread(target=first)
    t1.start()
    assert first_in_llm.wait(timeout=30)
    # the lease is fresh: a concurrent draft must be refused
    db = session_factory()
    with pytest.raises(RemediationConflictError):
        planner_module.draft_plan(db, session_factory, org_id, case_id)
    db.close()
    release_first.set()
    t1.join(timeout=30)
    assert outcomes["first"] == "VERIFIED"


def test_close_vs_lifecycle_race_stays_coherent(pg_env):
    """Concurrent close and lifecycle change serialize on the case lock: the
    final state is one of the two legal serial orders, never an interleaving
    (a CLOSED case with a freshly mutated action)."""
    session_factory, org_id, finding_id = pg_env
    case_id = _approved_case(session_factory, org_id, finding_id)
    llm_service.set_provider(DynamicFake([_plan_json()]))
    db = session_factory()
    plan = planner_module.draft_plan(db, session_factory, org_id, case_id)
    action_id = plan.actions[0].id
    actions_module.review_action(
        db, org_id, case_id, action_id, action="approve", priority="haute"
    )
    actions_module.change_lifecycle(
        db, org_id, case_id, action_id, lifecycle="IN_PROGRESS"
    )
    actions_module.change_lifecycle(db, org_id, case_id, action_id, lifecycle="DONE")
    db.close()

    barrier = threading.Barrier(2, timeout=10)
    outcomes: list = [None, None]

    def closer(slot: int) -> None:
        db = session_factory()
        try:
            barrier.wait()
            service_module.close_case(db, org_id, case_id, close_note="Fin.")
            outcomes[slot] = "closed"
        except RemediationConflictError:
            outcomes[slot] = "conflict"
        finally:
            db.close()

    def effectiveness(slot: int) -> None:
        db = session_factory()
        try:
            barrier.wait()
            actions_module.record_effectiveness(
                db, org_id, case_id, action_id,
                effectiveness="EFFECTIVE", note="Preuve.",
            )
            outcomes[slot] = "recorded"
        except RemediationConflictError:
            outcomes[slot] = "conflict"
        finally:
            db.close()

    threads = [
        threading.Thread(target=closer, args=(0,)),
        threading.Thread(target=effectiveness, args=(1,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    db = session_factory()
    case = db.get(RemediationCase, case_id)
    from app.models import RemediationAction

    action = db.get(RemediationAction, action_id)
    db.close()
    # legal serial orders only: close-then-refused, or record-then-closed
    if outcomes[1] == "recorded":
        assert case.status == "CLOSED" and action.effectiveness == "EFFECTIVE"
    else:
        assert outcomes == ["closed", "conflict"]
        assert case.status == "CLOSED" and action.effectiveness == "NOT_CHECKED"


def test_close_new_case_reopen_race(pg_env):
    """close -> new case -> reopen: concurrent reopen of the old case and
    creation of a new case for the same finding never yield two active
    cases (finding row locks in both paths)."""
    session_factory, org_id, finding_id = pg_env
    case_id = _approved_case(session_factory, org_id, finding_id)
    db = session_factory()
    service_module.close_case(db, org_id, case_id, close_note="Premier cas clos.")
    db.close()

    barrier = threading.Barrier(2, timeout=10)
    outcomes: list = [None, None]

    def reopener(slot: int) -> None:
        db = session_factory()
        try:
            barrier.wait()
            service_module.reopen_case(db, org_id, case_id)
            outcomes[slot] = "reopened"
        except RemediationConflictError:
            outcomes[slot] = "conflict"
        finally:
            db.close()

    def creator(slot: int) -> None:
        db = session_factory()
        try:
            barrier.wait()
            service_module.create_case(db, org_id, finding_id)
            outcomes[slot] = "created"
        except RemediationConflictError:
            outcomes[slot] = "conflict"
        finally:
            db.close()

    threads = [
        threading.Thread(target=reopener, args=(0,)),
        threading.Thread(target=creator, args=(1,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert outcomes.count("conflict") == 1, outcomes  # exactly one path won
    db = session_factory()
    active = db.scalars(
        select(RemediationCase)
        .join(RemediationCaseFinding, RemediationCaseFinding.case_id == RemediationCase.id)
        .where(
            RemediationCaseFinding.finding_id == finding_id,
            RemediationCase.status != "CLOSED",
        )
    ).all()
    db.close()
    assert len(active) == 1


def _approved_action_pg(session_factory, org_id, case_id):
    """VERIFIED plan + human-approved action, PG flavour. Returns
    (action_id, document_id)."""
    from tests.test_remediation_planner import DynamicFake as _DF, _plan_json as _pj

    llm_service.set_provider(_DF([_pj()]))
    db = session_factory()
    plan = planner_module.draft_plan(db, session_factory, org_id, case_id)
    assert plan.status == "VERIFIED"
    action_id = plan.actions[0].id
    actions_module.review_action(
        db, org_id, case_id, action_id, action="approve", priority="haute"
    )
    doc_id = db.scalar(select(Document.id).where(Document.organization_id == org_id))
    db.close()
    return action_id, doc_id


def test_concurrent_patch_approvals_share_one_base(pg_env):
    """Two VERIFIED proposals over the same base version, decided
    concurrently under real row locks: exactly ONE version activates; the
    loser is a typed conflict or a terminal ABANDONED(stale_base) — never a
    second ACTIVE version (one-ACTIVE partial unique is the backstop)."""
    import json as _json

    from app.models import DocumentVersion, PatchProposal
    from app.remediation import patcher as patcher_module
    from tests.test_remediation_planner import DynamicFake as _DF

    session_factory, org_id, finding_id = pg_env
    case_id = _approved_case(session_factory, org_id, finding_id)
    action_id, doc_id = _approved_action_pg(session_factory, org_id, case_id)

    anchor = "Politique IA de test."

    def _patch_json(new_text: str) -> str:
        return _json.dumps(
            {
                "anchor_quote": anchor,
                "anchor_page": 1,
                "operation": "insert_after",
                "new_text_fr": new_text,
                "rationale": "Compléter la politique.",
            },
            ensure_ascii=False,
        )

    proposals = []
    for text in (
        "Les incidents sont consignés dans un registre revu chaque mois.",
        "Un plan de contrôle des fournisseurs est ajouté à la politique.",
    ):
        llm_service.set_provider(_DF([_patch_json(text)]))
        db = session_factory()
        proposal = patcher_module.draft_patch_proposal(
            db, session_factory, org_id, case_id, action_id, doc_id
        )
        assert proposal.status == "VERIFIED"
        proposals.append(proposal.id)
        db.close()

    barrier = threading.Barrier(2, timeout=10)
    results: list = [None, None]

    def worker(slot: int, proposal_id: str) -> None:
        db = session_factory()
        try:
            barrier.wait()
            out = patcher_module.decide_patch(
                db, org_id, case_id, proposal_id, decision="approve"
            )
            results[slot] = ("ok", out["outcome"])
        except RemediationConflictError as exc:
            results[slot] = ("conflict", str(exc))
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=(i, pid))
        for i, pid in enumerate(proposals)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    outcomes = sorted(str(r) for r in results)
    winners = [r for r in results if r == ("ok", "activated")]
    assert len(winners) == 1, results
    loser = next(r for r in results if r != ("ok", "activated"))
    assert loser[0] == "conflict" or loser[1].startswith("abandoned:"), results

    db = session_factory()
    active = db.scalars(
        select(DocumentVersion).where(
            DocumentVersion.document_id == doc_id,
            DocumentVersion.state == "ACTIVE",
        )
    ).all()
    assert len(active) == 1 and active[0].origin == "patch"
    db.close()


def _seed_docx(session_factory, org_id: str, checksum: str = "docx-base"):
    """A parsed DOCX-format document (canonical_format derives from the .docx
    filename; no real docx bytes needed for the version row)."""
    from tests.conftest import seed_parsed_document

    db = session_factory()
    doc = seed_parsed_document(
        db, org_id, "politique.docx", ["Politique documentaire initiale."], checksum=checksum
    )
    doc_id, base_vid = doc.id, doc.current_version_id
    db.close()
    return doc_id, base_vid


def _artifact_json(content: str = "## Révision\n\nNouveau paragraphe.") -> str:
    import json as _json

    return _json.dumps(
        {"content_md": content, "rationale": "Couvre l'action approuvée."},
        ensure_ascii=False,
    )


def _verified_artifact_pg(session_factory, org_id, case_id, action_id, docx_id):
    from app.remediation import patcher as patcher_module
    from tests.test_remediation_planner import DynamicFake as _DF

    llm_service.set_provider(_DF([_artifact_json()]))
    db = session_factory()
    artifact = patcher_module.draft_artifact(
        db, session_factory, org_id, case_id, action_id, docx_id
    )
    assert artifact.status == "VERIFIED", artifact.abstain_reason
    artifact_id = artifact.id
    db.close()
    return artifact_id


def test_supersede_upload_with_artifact_lineage_pg(pg_env):
    """The PDF/DOCX corrective-action loop on real Postgres: a VERIFIED
    artifact -> human superseding upload citing it -> new version ACTIVE with
    source_artifact_id lineage, base SUPERSEDED, and BOTH audit streams emit
    version_superseded_by_upload (the composite FKs + dual events never ran on
    PG before)."""
    from app.models import (
        DocumentVersion,
        DocumentVersionEvent,
        RemediationEvent,
    )
    from app.remediation import patcher as patcher_module

    session_factory, org_id, finding_id = pg_env
    case_id = _approved_case(session_factory, org_id, finding_id)
    action_id, _txt = _approved_action_pg(session_factory, org_id, case_id)
    docx_id, base_vid = _seed_docx(session_factory, org_id)
    artifact_id = _verified_artifact_pg(session_factory, org_id, case_id, action_id, docx_id)

    db = session_factory()
    out = patcher_module.supersede_upload(
        db,
        org_id,
        supersedes_version_id=base_vid,
        remediation_artifact_id=artifact_id,
        filename="politique.docx",
        data=b"contenu docx revise",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        pages=["Politique documentaire révisée par un humain."],
        canonical_format="docx",
    )
    assert out["outcome"] == "activated", out
    new_vid = out["version_id"]
    db.close()

    db = session_factory()
    new = db.get(DocumentVersion, new_vid)
    base = db.get(DocumentVersion, base_vid)
    doc = db.get(Document, docx_id)
    assert new.state == "ACTIVE" and new.origin == "upload"
    assert new.source_artifact_id == artifact_id  # lineage persisted (RESTRICT FK)
    assert base.state == "SUPERSEDED"
    assert doc.current_version_id == new_vid
    # document_version_events stream carries the supersession
    vevents = [
        e.event_type
        for e in db.scalars(
            select(DocumentVersionEvent)
            .where(DocumentVersionEvent.document_id == docx_id)
            .order_by(DocumentVersionEvent.sequence)
        )
    ]
    assert "version_superseded_by_upload" in vevents
    assert vevents[-3:] == ["version_indexed", "version_activated", "version_superseded_by_upload"]
    # case-scoped remediation event references the artifact + both versions
    case_ev = db.scalars(
        select(RemediationEvent).where(
            RemediationEvent.case_id == case_id,
            RemediationEvent.event_type == "version_superseded_by_upload",
        )
    ).all()
    assert len(case_ev) == 1
    payload = case_ev[0].payload
    assert payload["artifact_id"] == artifact_id
    assert payload["superseded_version_id"] == base_vid
    assert payload["new_version_id"] == new_vid
    assert payload["document_version_event_id"]  # correlates the two streams
    # NB the source_artifact_id lineage value is persisted here, but the
    # RESTRICT FK itself is a POST-HOC circular FK that Base.metadata.create_all
    # (this fixture) does not build — its enforcement is asserted against the
    # alembic-built DB in test_migrations.test_0014_backfills_document_versions.
    db.close()


def test_supersede_upload_authority_lost_between_tx_a_and_tx_b_pg(pg_env):
    """Round-4 gate on PG: the action/plan/evidence can change during the
    lock-free indexing window; Tx B's artifact-authority recheck must catch it
    and mark the candidate ABANDONED(authority_lost) rather than activate a
    revision whose corrective-action lineage no longer holds."""
    from app.models import DocumentVersion, RemediationCase
    from app.remediation import patcher as patcher_module

    session_factory, org_id, finding_id = pg_env
    case_id = _approved_case(session_factory, org_id, finding_id)
    action_id, _txt = _approved_action_pg(session_factory, org_id, case_id)
    docx_id, base_vid = _seed_docx(session_factory, org_id)
    artifact_id = _verified_artifact_pg(session_factory, org_id, case_id, action_id, docx_id)

    # Inject a concurrent authority change in the lock-free window: bump the
    # case evidence_revision after indexing but before Tx B.
    real_index = patcher_module._index_candidate_points

    def racing_index(db, org, version_id, token):
        real_index(db, org, version_id, token)
        other = session_factory()
        try:
            case = other.get(RemediationCase, case_id, with_for_update=True)
            case.evidence_revision += 1
            other.commit()
        finally:
            other.close()

    patcher_module._index_candidate_points = racing_index
    try:
        db = session_factory()
        out = patcher_module.supersede_upload(
            db,
            org_id,
            supersedes_version_id=base_vid,
            remediation_artifact_id=artifact_id,
            filename="politique.docx",
            data=b"contenu docx revise 2",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            pages=["Politique révisée alors que le contexte a changé."],
            canonical_format="docx",
        )
    finally:
        patcher_module._index_candidate_points = real_index
    assert out["outcome"] == "abandoned:authority_lost", out
    cand_vid = out["version_id"]
    db.close()

    db = session_factory()
    cand = db.get(DocumentVersion, cand_vid)
    base = db.get(DocumentVersion, base_vid)
    doc = db.get(Document, docx_id)
    assert cand.state == "ABANDONED" and cand.abandoned_reason == "authority_lost"
    assert base.state == "ACTIVE"  # the base version was never displaced
    assert doc.current_version_id == base_vid
    db.close()

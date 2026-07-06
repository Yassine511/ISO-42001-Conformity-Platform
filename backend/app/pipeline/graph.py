"""M3 pipeline graph: retrieve -> judge -> verify (+ bounded repair loop).

Checkpointer notes:
- PostgresSaver tables are LIBRARY-OWNED (created by .setup()), deliberately
  outside Alembic — never write migrations for them.
- settings.database_url is an SQLAlchemy URL ("postgresql+psycopg://…");
  psycopg rejects that form, so to_psycopg_dsn() strips the driver suffix.
- PostgresSaver.from_conn_string() is a context manager: use
  checkpointer_lifespan() around compile + invoke (the CLI enters it for its
  whole run). Set LANGGRAPH_STRICT_MSGPACK=true in the environment (done in
  docker-compose; export it before CLI runs) so checkpoint deserialization is
  strict — the state only carries primitives, so nothing legitimate is lost.
"""

from contextlib import contextmanager
from datetime import datetime, timezone

from langgraph.graph import END, StateGraph
from sqlalchemy import select

from app.config import settings
from app.models import Assessment, AssessmentAttempt, Document, DocumentStatus, Finding, Organization
from app.pipeline.dev_split import DEV_REQUIREMENT_IDS, is_dev_requirement
from app.pipeline.nodes import (
    SessionFactory,
    make_judge_node,
    make_retrieve_node,
    make_verify_node,
    route_after_verify,
)
from app.pipeline.state import (
    AssessmentNotRunningError,
    AssessmentResult,
    AssessmentStatus,
    GovernanceState,
    QuoteMatch,
)
from app.services.chunking import CHUNKER_VERSION
from app.services.retrieval import drop_stale_points, load_kb, sync_index


class AssessmentAlreadyRunningError(ValueError):
    """An assessment is already RUNNING for this organization. Raised by the
    pre-check under the org row lock; the DB partial unique index
    (uq_assessments_one_running) is the concurrency backstop — callers map its
    IntegrityError to the same condition."""


class CorpusVersionMismatchError(ValueError):
    """The KB corpus_version changed after the assessment was created.

    Permanent for the assessment: no retry or resume can succeed, so callers
    must finalize it FAILED (a bare exception would leave it RUNNING forever,
    with every resume attempt hitting the same guard)."""


def to_psycopg_dsn(url: str) -> str:
    """SQLAlchemy URL -> plain libpq DSN (psycopg rejects '+driver' schemes)."""
    scheme, sep, rest = url.partition("://")
    return scheme.split("+", 1)[0] + sep + rest


@contextmanager
def checkpointer_lifespan():
    """Application-lifetime PostgresSaver; compile and invoke INSIDE this."""
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(to_psycopg_dsn(settings.database_url)) as saver:
        saver.setup()  # idempotent; library-owned tables
        yield saver


def build_graph(session_factory: SessionFactory, checkpointer=None):
    graph = StateGraph(GovernanceState)
    graph.add_node("retrieve", make_retrieve_node(session_factory))
    graph.add_node("judge", make_judge_node(session_factory))
    graph.add_node("verify", make_verify_node(session_factory))
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "judge")
    graph.add_edge("judge", "verify")
    graph.add_conditional_edges("verify", route_after_verify, {"end": END, "judge": "judge"})
    return graph.compile(checkpointer=checkpointer)


# ------------------------------------------------------------- lifecycle API


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_assessment(
    session_factory: SessionFactory,
    org_id: str,
    requirement_ids: list[str] | None = None,
    *,
    k: int = 6,
    allow_holdout: bool = False,
) -> str:
    """Create a RUNNING assessment with its frozen run contract.

    requirement_ids is the run MANIFEST: what this assessment is meant to
    cover. Resume paths validate against it (see resume_manifest). Creation is
    ATOMIC with indexing: the org row is locked, the org's documents are
    reconciled into the index (sync_index, no commit), and the assessment row
    with its frozen document_manifest and retrieval_k is committed in the same
    transaction — so the manifest records exactly what the run retrieves from.

    M6 holdout protection: ids outside the frozen dev split are rejected
    unless allow_holdout=True (reserved for the M6 evaluation script; no HTTP
    route exposes it).
    """
    kb = load_kb()
    if not 1 <= k <= 20:
        raise ValueError(f"profondeur de récupération invalide : k={k} (borne 1-20).")
    if requirement_ids is not None:
        if not requirement_ids:
            raise ValueError("manifeste vide : précisez au moins une exigence.")
        # a duplicated id would inflate the manifest total and make full
        # coverage unreachable — reject rather than silently dedup
        duplicates = sorted({rid for rid in requirement_ids if requirement_ids.count(rid) > 1})
        if duplicates:
            raise ValueError(
                "exigence(s) en double dans le manifeste : " + ", ".join(duplicates)
            )
        # Validate the manifest at creation: an unknown id would otherwise leave
        # the assessment RUNNING forever (run_requirement raises "exigence
        # inconnue" for it every resume, and coverage is never reached).
        unknown = [rid for rid in requirement_ids if rid not in kb["by_id"]]
        if unknown:
            raise ValueError(
                "exigence(s) inconnue(s) dans la base ISO 42001 : " + ", ".join(unknown)
            )
        if not allow_holdout:
            held_out = [rid for rid in requirement_ids if not is_dev_requirement(rid)]
            if held_out:
                raise ValueError(
                    "exigence(s) réservée(s) au jeu de test M6 (gelé jusqu'à "
                    "l'évaluation) : " + ", ".join(held_out)
                )
    db = session_factory()
    try:
        # Org row lock: serializes creation against document upload/delete,
        # /index and concurrent creation (see services/run_guard.py).
        org = db.get(Organization, org_id, with_for_update=True)
        if org is None:
            raise ValueError(f"organisation inconnue : {org_id}")
        running = db.scalar(
            select(Assessment.id).where(
                Assessment.organization_id == org_id,
                Assessment.status == AssessmentStatus.RUNNING.value,
            )
        )
        if running is not None:
            raise AssessmentAlreadyRunningError(
                "une évaluation est déjà en cours pour cette organisation "
                f"({running}) ; terminez-la ou abandonnez-la d'abord."
            )
        report, stale_point_ids = sync_index(db, org_id)
        if report["documents"] == 0:
            raise ValueError(
                "aucun document analysé pour cette organisation : téléversez "
                "au moins une politique avant de lancer une évaluation."
            )
        docs = db.scalars(
            select(Document).where(
                Document.organization_id == org_id,
                Document.status == DocumentStatus.PARSED.value,
            )
        ).all()
        assessment = Assessment(
            organization_id=org_id,
            corpus_version=kb["corpus_version"],
            status=AssessmentStatus.RUNNING.value,
            requirement_ids=requirement_ids,
            retrieval_k=k,
            document_manifest={
                "documents": [
                    {
                        "document_id": d.id,
                        "filename": d.filename,
                        "checksum": d.checksum,
                        "parser_version": d.parser_version,
                        "page_count": d.page_count,
                    }
                    for d in docs
                ],
                "chunker_version": CHUNKER_VERSION,
                "chunk_count": report["chunks"],
                "indexed_at": _now().isoformat(),
            },
        )
        db.add(assessment)
        db.commit()
        assessment_id = assessment.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    # After the commit: a failure here is reconciliation debt, never a failed
    # creation (see drop_stale_points docstring).
    try:
        drop_stale_points(stale_point_ids)
    except Exception:  # pragma: no cover - best-effort cleanup
        import logging

        logging.getLogger(__name__).warning(
            "stale-point cleanup failed after assessment creation; "
            "next /index will reconcile",
            exc_info=True,
        )
    return assessment_id


def adopt_manifest(
    session_factory: SessionFactory, assessment_id: str, requirement_ids: list[str]
) -> None:
    """One-time manifest adoption for a legacy (pre-manifest) RUNNING row: the
    CLI resume path validates the explicit selection via resume_manifest, then
    persists it so the shared runner (which reads the row) can execute it.
    No-op when a manifest already exists — the stored manifest stays
    authoritative."""
    db = session_factory()
    try:
        assessment = db.get(Assessment, assessment_id, with_for_update=True)
        if assessment is None:
            raise ValueError(f"assessment inconnu : {assessment_id}")
        if not assessment.requirement_ids:
            assessment.requirement_ids = list(requirement_ids)
            db.commit()
    finally:
        db.close()


def resume_manifest(
    session_factory: SessionFactory,
    assessment_id: str,
    requested_ids: list[str] | None,
) -> list[str]:
    """Requirement ids to run when resuming an assessment.

    The stored manifest is authoritative: resuming with a DIFFERENT selection
    would finalize the assessment while its planned requirements stay
    unfinished. A selection may be passed only if it matches the manifest;
    legacy assessments without a manifest require an explicit selection.
    """
    db = session_factory()
    try:
        assessment = db.get(Assessment, assessment_id)
        if assessment is None:
            raise ValueError(f"assessment inconnu : {assessment_id}")
        stored = assessment.requirement_ids
    finally:
        db.close()
    if stored:
        if requested_ids is not None and list(requested_ids) != list(stored):
            raise ValueError(
                "la sélection demandée ne correspond pas au manifeste de "
                f"l'assessment ({len(stored)} exigence(s) planifiée(s)) ; "
                "reprenez sans sélection ou créez un nouvel assessment."
            )
        return list(stored)
    if requested_ids is None:
        raise ValueError(
            "assessment sans manifeste (créé avant cette version) : "
            "précisez explicitement la sélection d'exigences."
        )
    return list(requested_ids)


def finalize_assessment(
    session_factory: SessionFactory,
    assessment_id: str,
    status: AssessmentStatus,
    error: str | None = None,
) -> bool:
    """Caller states the outcome explicitly: an ABSTAINED finding is a
    completed pipeline execution — only unhandled operational failures are
    FAILED.

    Locks the assessment row (FOR UPDATE): finalization and finding creation
    (nodes._persist_finding takes the same lock) are mutually exclusive, so a
    finding can never land in an assessment this call just finalized.

    Terminal states are immutable: only a RUNNING row can transition. Returns
    False (no write) when the row is already COMPLETED/FAILED — a caller whose
    RUNNING check raced a concurrent finalization (e.g. the abandon endpoint
    vs the runner finishing) must never rewrite the outcome."""
    db = session_factory()
    try:
        assessment = db.get(Assessment, assessment_id, with_for_update=True)
        if assessment is None:
            raise ValueError(f"assessment inconnu : {assessment_id}")
        if assessment.status != AssessmentStatus.RUNNING.value:
            db.rollback()
            return False
        assessment.status = status.value
        assessment.error = error
        assessment.finished_at = _now()
        # cancel_requested is a REQUEST flag, meaningless once terminal (a
        # honoured cancellation is recorded in error/status): clearing it here
        # keeps terminal metadata canonical even when an abandon set the flag
        # concurrently with this finalization.
        assessment.cancel_requested = False
        db.commit()
        return True
    finally:
        db.close()


def resolve_run_status(total: int, infra_abstains: int) -> AssessmentStatus:
    """Final status of a fully-covered run: evidentiary abstention is a valid
    outcome -> COMPLETED; a run where EVERY finding is an infrastructure
    failure (llm_error/rate_limited) failed as a whole. This decision lives
    here — not in callers — so the CLI and the M4 API cannot diverge."""
    if total > 0 and infra_abstains >= total:
        return AssessmentStatus.FAILED
    return AssessmentStatus.COMPLETED


def unfinished_requirements(
    session_factory: SessionFactory, assessment_id: str, requirement_ids: list[str]
) -> list[str]:
    """Manifest requirements that do NOT yet have a terminal finding.

    Finalization must require full coverage: completing an assessment while a
    planned requirement produced no finding would silently drop it (and block
    resume, since resume demands RUNNING)."""
    db = session_factory()
    try:
        done = set(
            db.scalars(
                select(Finding.requirement_id).where(Finding.assessment_id == assessment_id)
            ).all()
        )
    finally:
        db.close()
    return [rid for rid in requirement_ids if rid not in done]


def note_assessment_error(
    session_factory: SessionFactory, assessment_id: str, error: str
) -> None:
    """Record an error WITHOUT changing status: the assessment stays RUNNING
    and therefore resumable — FAILED is reserved for runs abandoned for good.

    Only a RUNNING row is written (row lock, same discipline as
    finalize_assessment): a late runner crash must never stamp its error onto
    an assessment that was finalized concurrently — terminal metadata is
    immutable."""
    db = session_factory()
    try:
        assessment = db.get(Assessment, assessment_id, with_for_update=True)
        if assessment is not None and assessment.status == AssessmentStatus.RUNNING.value:
            assessment.error = error
            db.commit()
    finally:
        db.close()


def _result_from_row(session_factory: SessionFactory, row: Finding) -> AssessmentResult:
    db = session_factory()
    try:
        attempts = db.scalars(
            select(AssessmentAttempt)
            .where(
                AssessmentAttempt.assessment_id == row.assessment_id,
                AssessmentAttempt.requirement_id == row.requirement_id,
            )
            .order_by(AssessmentAttempt.attempt_number)
        ).all()
        history = [
            {
                "attempt": a.attempt_number,
                "prompt_version": a.prompt_version,
                "parsed_ok": a.parsed_ok,
                "verifier_errors": a.verifier_errors,
            }
            for a in attempts
        ]
    finally:
        db.close()
    match = None
    if row.matched_chunk_id is not None:
        match = QuoteMatch(
            chunk_id=row.matched_chunk_id,
            match_start=row.match_start,
            match_end=row.match_end,
            method=row.match_method,
            score=row.match_score,
        )
    return AssessmentResult(
        finding_id=row.id,
        assessment_id=row.assessment_id,
        requirement_id=row.requirement_id,
        status=row.status,
        verdict=row.verdict,
        abstain_reason=row.abstain_reason,
        policy_quote=row.policy_quote,
        clause_ref=row.clause_ref,
        confidence=row.confidence,
        rationale=row.rationale,
        match=match,
        attempts=row.attempts,
        final_model=row.final_model,
        final_provider=row.final_provider,
        retrieved=row.retrieved or [],
        attempt_history=history,
        audit_log=row.audit_log or [],
    )


def run_requirement(
    session_factory: SessionFactory,
    assessment_id: str,
    requirement_id: str,
    *,
    k: int = 6,
    checkpointer=None,
    compiled_graph=None,
    on_node=None,
) -> AssessmentResult:
    """Run the pipeline for one requirement of an existing assessment.

    Terminal idempotency: if a terminal finding already exists for
    (assessment_id, requirement_id), it is returned WITHOUT invoking the
    graph — re-running a batch never duplicates work or rows.

    on_node(node_name) is called as each graph node completes (best-effort
    progress decoration; exceptions in it are swallowed). The final state is
    identical to the invoke() path: streaming uses stream_mode "values", whose
    last emission IS the final aggregated state.
    """
    db = session_factory()
    try:
        assessment = db.get(Assessment, assessment_id)
        if assessment is None:
            raise ValueError(f"assessment inconnu : {assessment_id}")
        org_id = assessment.organization_id
        assessment_corpus_version = assessment.corpus_version
        assessment_status = assessment.status
        assessment_manifest = assessment.requirement_ids
        existing = db.scalars(
            select(Finding).where(
                Finding.assessment_id == assessment_id,
                Finding.requirement_id == requirement_id,
            )
        ).first()
    finally:
        db.close()
    # Idempotency: reading back an already-terminal finding is always safe,
    # even on a COMPLETED/FAILED assessment (M4 result display re-reads these).
    if existing is not None:
        return _result_from_row(session_factory, existing)

    # Lifecycle guard: a NEW finding may only be created on a RUNNING assessment
    # that actually planned this requirement. Without this, a COMPLETED
    # assessment silently accepts an out-of-manifest finding and stays COMPLETED
    # (corrupt lifecycle), and an off-manifest requirement inflates coverage.
    if assessment_status != AssessmentStatus.RUNNING.value:
        # Fast path only (non-authoritative): avoids a paid LLM call on an
        # already-terminal assessment. The race-closing check is under the row
        # lock in _persist_finding.
        raise AssessmentNotRunningError(
            f"assessment non modifiable : statut {assessment_status} "
            f"(RUNNING requis pour produire un nouveau constat)."
        )
    if assessment_manifest is not None and requirement_id not in assessment_manifest:
        raise ValueError(
            f"exigence hors manifeste : « {requirement_id} » ne fait pas partie "
            f"des {len(assessment_manifest)} exigence(s) planifiée(s) pour cet "
            f"assessment ; créez un nouvel assessment pour l'évaluer."
        )

    kb = load_kb()
    # Provenance guard: a long-running assessment must not silently mix
    # requirement definitions from different corpus versions.
    if kb["corpus_version"] != assessment_corpus_version:
        raise CorpusVersionMismatchError(
            f"corpus_version a changé pendant l'assessment : "
            f"{assessment_corpus_version} (assessment) != {kb['corpus_version']} (KB) ; "
            f"créez un nouvel assessment."
        )
    entry = kb["by_id"].get(requirement_id)
    if entry is None:
        raise ValueError(f"exigence inconnue dans la base ISO 42001 : {requirement_id}")

    graph = compiled_graph or build_graph(session_factory, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": f"{assessment_id}:{requirement_id}"}}

    # Application-level resume: if a checkpointed run for this thread is
    # mid-flight (interrupted or crashed), continue it with invoke(None) —
    # re-submitting the initial state would RERUN prior nodes, not resume.
    if getattr(graph, "checkpointer", None):
        snapshot = graph.get_state(config)
        if snapshot is not None and snapshot.next:
            final_state = graph.invoke(None, config)
            return _result_from_final(
                session_factory, final_state, assessment_id, requirement_id
            )

    initial: GovernanceState = {
        "assessment_id": assessment_id,
        "organization_id": org_id,
        "requirement_id": requirement_id,
        "requirement_text": entry["requirement_fr"],
        "requirement_domain": entry.get("domain"),
        "corpus_version": kb["corpus_version"],
        "retrieval_k": k,
        "judge_attempts": 0,
        "verification_errors": [],
        "draft": None,
        "finding": None,
        "audit_log": [],
        "attempt_history": [],
    }
    if on_node is None:
        final_state = graph.invoke(initial, config)
    else:
        final_state = None
        for mode, payload in graph.stream(
            initial, config, stream_mode=["updates", "values"]
        ):
            if mode == "updates":
                for node_name in payload:
                    try:
                        on_node(node_name)
                    except Exception:  # progress must never abort the run
                        pass
            else:
                final_state = payload
    return _result_from_final(session_factory, final_state, assessment_id, requirement_id)


def _result_from_final(
    session_factory: SessionFactory,
    final_state: dict,
    assessment_id: str,
    requirement_id: str,
) -> AssessmentResult:
    """Build the AssessmentResult after a graph run. A duplicate execution that
    LOST the write race (see nodes._persist_finding) must report the persisted
    row in full — model/provider attribution and evidence included — so the
    winner's canonical verdict is never attributed to the loser's provider."""
    finding = final_state.get("finding") or {}
    if finding.get("canonical_from_row"):
        db = session_factory()
        try:
            row = db.get(Finding, finding["finding_id"])
        finally:
            db.close()
        if row is not None:
            return _result_from_row(session_factory, row)
    return _result_from_state(final_state, assessment_id, requirement_id)


def _result_from_state(
    final_state: dict, assessment_id: str, requirement_id: str
) -> AssessmentResult:
    finding = final_state.get("finding") or {}
    match = None
    if finding.get("match"):
        match = QuoteMatch(**finding["match"])
    return AssessmentResult(
        finding_id=finding.get("finding_id", ""),
        assessment_id=assessment_id,
        requirement_id=requirement_id,
        status=finding.get("status", ""),
        verdict=finding.get("verdict"),
        abstain_reason=finding.get("abstain_reason"),
        policy_quote=finding.get("policy_quote"),
        clause_ref=finding.get("clause_ref"),
        confidence=finding.get("confidence"),
        rationale=finding.get("rationale"),
        match=match,
        attempts=finding.get("attempts", 0),
        final_model=final_state.get("final_model"),
        final_provider=final_state.get("final_provider"),
        retrieved=final_state.get("retrieved") or [],
        attempt_history=final_state.get("attempt_history") or [],
        audit_log=final_state.get("audit_log") or [],
    )

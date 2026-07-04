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
from app.models import Assessment, AssessmentAttempt, Finding
from app.pipeline.nodes import (
    SessionFactory,
    make_judge_node,
    make_retrieve_node,
    make_verify_node,
    route_after_verify,
)
from app.pipeline.state import AssessmentResult, AssessmentStatus, GovernanceState, QuoteMatch
from app.services.retrieval import load_kb


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


def create_assessment(session_factory: SessionFactory, org_id: str) -> str:
    kb = load_kb()
    db = session_factory()
    try:
        assessment = Assessment(
            organization_id=org_id,
            corpus_version=kb["corpus_version"],
            status=AssessmentStatus.RUNNING.value,
        )
        db.add(assessment)
        db.commit()
        return assessment.id
    finally:
        db.close()


def finalize_assessment(
    session_factory: SessionFactory,
    assessment_id: str,
    status: AssessmentStatus,
    error: str | None = None,
) -> None:
    """Caller states the outcome explicitly: an ABSTAINED finding is a
    completed pipeline execution — only unhandled operational failures are
    FAILED."""
    db = session_factory()
    try:
        assessment = db.get(Assessment, assessment_id)
        if assessment is None:
            raise ValueError(f"assessment inconnu : {assessment_id}")
        assessment.status = status.value
        assessment.error = error
        assessment.finished_at = _now()
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
        audit_log=[],
    )


def run_requirement(
    session_factory: SessionFactory,
    assessment_id: str,
    requirement_id: str,
    *,
    k: int = 6,
    checkpointer=None,
    compiled_graph=None,
) -> AssessmentResult:
    """Run the pipeline for one requirement of an existing assessment.

    Terminal idempotency: if a terminal finding already exists for
    (assessment_id, requirement_id), it is returned WITHOUT invoking the
    graph — re-running a batch never duplicates work or rows.
    """
    db = session_factory()
    try:
        assessment = db.get(Assessment, assessment_id)
        if assessment is None:
            raise ValueError(f"assessment inconnu : {assessment_id}")
        org_id = assessment.organization_id
        assessment_corpus_version = assessment.corpus_version
        existing = db.scalars(
            select(Finding).where(
                Finding.assessment_id == assessment_id,
                Finding.requirement_id == requirement_id,
            )
        ).first()
    finally:
        db.close()
    if existing is not None:
        return _result_from_row(session_factory, existing)

    kb = load_kb()
    # Provenance guard: a long-running assessment must not silently mix
    # requirement definitions from different corpus versions.
    if kb["corpus_version"] != assessment_corpus_version:
        raise ValueError(
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
            return _result_from_state(final_state, assessment_id, requirement_id)

    initial: GovernanceState = {
        "assessment_id": assessment_id,
        "organization_id": org_id,
        "requirement_id": requirement_id,
        "requirement_text": entry["requirement_fr"],
        "corpus_version": kb["corpus_version"],
        "retrieval_k": k,
        "judge_attempts": 0,
        "verification_errors": [],
        "draft": None,
        "finding": None,
        "audit_log": [],
        "attempt_history": [],
    }
    final_state = graph.invoke(initial, config)
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

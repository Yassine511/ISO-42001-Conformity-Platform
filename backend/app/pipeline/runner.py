"""Shared assessment runner (M5): one loop for the CLI and the HTTP API.

The persisted Assessment row is the run contract: run_assessment() loads the
requirement manifest and retrieval_k from PostgreSQL — callers cannot pass
values that disagree with the row. Loop semantics (operational failures
continue, corpus mismatch finalizes FAILED, full coverage required before
finalization, COMPLETED/FAILED quality decision in resolve_run_status) are the
former scripts/assess_demo.py loop, extracted here so CLI and API cannot
diverge.

Resume correctness: totals come from the complete manifest, aggregate counts
are initialized from EXISTING findings and re-queried authoritatively before
finalization — a resumed run is judged on all its findings, not just the
newly executed ones.

Cooperative cancellation: Assessment.cancel_requested is re-read between
requirements and once more before finalization; when set the run finalizes
FAILED («Annulée par l'utilisateur.»).

In-process execution state (_THREADS/PROGRESS) is best-effort decoration for
the polling API — never a correctness mechanism (the DB partial unique index
and row statuses are authoritative).
"""

import logging
import threading
from dataclasses import dataclass

from sqlalchemy import select

from app.models import Assessment, Finding
from app.pipeline.graph import (
    AssessmentNotRunningError,
    CorpusVersionMismatchError,
    build_graph,
    finalize_assessment,
    note_assessment_error,
    resolve_run_status,
    run_requirement,
)
from app.pipeline.nodes import SessionFactory
from app.pipeline.state import AssessmentStatus, is_infrastructure_failure

logger = logging.getLogger(__name__)

CANCELLED_ERROR = "Annulée par l'utilisateur."

# assessment_id -> {"requirement_id", "node", "done", "total"} — best-effort,
# lost on restart; the DB rows remain the ground truth for progress.
PROGRESS: dict[str, dict] = {}
_THREADS: dict[str, threading.Thread] = {}
_LOCK = threading.Lock()


@dataclass
class AssessmentRunResult:
    """Outcome of one run_assessment() call (post-run row status + tallies)."""

    status: str  # RUNNING | COMPLETED | FAILED
    done: int
    total: int
    verified: int
    abstained: int
    operational_failures: int
    infra_abstains: int
    error: str | None


def _cancel_requested(session_factory: SessionFactory, assessment_id: str) -> bool:
    db = session_factory()
    try:
        return bool(
            db.scalar(select(Assessment.cancel_requested).where(Assessment.id == assessment_id))
        )
    finally:
        db.close()


def _aggregate(session_factory: SessionFactory, assessment_id: str) -> dict:
    """Authoritative per-status tallies from the findings table."""
    db = session_factory()
    try:
        rows = db.execute(
            select(Finding.requirement_id, Finding.status, Finding.abstain_reason).where(
                Finding.assessment_id == assessment_id
            )
        ).all()
    finally:
        db.close()
    return {
        "done_ids": {r.requirement_id for r in rows},
        "verified": sum(1 for r in rows if r.status == "VERIFIED"),
        "abstained": sum(1 for r in rows if r.status == "ABSTAINED"),
        "infra_abstains": sum(1 for r in rows if is_infrastructure_failure(r.abstain_reason)),
    }


def run_assessment(
    session_factory: SessionFactory,
    assessment_id: str,
    *,
    checkpointer=None,
    compiled_graph=None,
    on_progress=None,
    on_result=None,
) -> AssessmentRunResult:
    """Execute an assessment's unfinished requirements to completion.

    on_progress(requirement_id, node, done, total) and on_result(result) are
    best-effort callbacks (progress display / CLI printing); their exceptions
    are logged and never abort the run.
    """
    db = session_factory()
    try:
        assessment = db.get(Assessment, assessment_id)
        if assessment is None:
            raise ValueError(f"assessment inconnu : {assessment_id}")
        manifest = list(assessment.requirement_ids or [])
        k = assessment.retrieval_k or 6
    finally:
        db.close()
    if not manifest:
        raise ValueError(
            "manifeste incomplet : cet assessment (antérieur à M5) n'a pas de "
            "manifeste d'exigences ; adoptez-en un explicitement (CLI) ou créez "
            "un nouvel assessment."
        )

    total = len(manifest)
    agg = _aggregate(session_factory, assessment_id)
    done_ids = agg["done_ids"]
    failures = 0

    def notify(requirement_id: str, node: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(requirement_id, node, len(done_ids), total)
        except Exception:
            logger.warning("on_progress callback failed", exc_info=True)

    def emit(result) -> None:
        if on_result is None:
            return
        try:
            on_result(result)
        except Exception:
            logger.warning("on_result callback failed", exc_info=True)

    def _result(status: str, error: str | None) -> AssessmentRunResult:
        final = _aggregate(session_factory, assessment_id)
        return AssessmentRunResult(
            status=status,
            done=len(final["done_ids"]),
            total=total,
            verified=final["verified"],
            abstained=final["abstained"],
            operational_failures=failures,
            infra_abstains=final["infra_abstains"],
            error=error,
        )

    graph = compiled_graph or build_graph(session_factory, checkpointer=checkpointer)

    for requirement_id in [rid for rid in manifest if rid not in done_ids]:
        if _cancel_requested(session_factory, assessment_id):
            finalize_assessment(
                session_factory, assessment_id, AssessmentStatus.FAILED, error=CANCELLED_ERROR
            )
            return _result(AssessmentStatus.FAILED.value, CANCELLED_ERROR)
        notify(requirement_id, "retrieve")
        try:
            result = run_requirement(
                session_factory,
                assessment_id,
                requirement_id,
                k=k,
                compiled_graph=graph,
                on_node=lambda node, rid=requirement_id: notify(rid, node),
            )
        except CorpusVersionMismatchError as exc:
            # permanent: no resume can succeed — leaving the assessment RUNNING
            # would trap it in an unresumable loop
            finalize_assessment(
                session_factory, assessment_id, AssessmentStatus.FAILED, error=str(exc)
            )
            return _result(AssessmentStatus.FAILED.value, str(exc))
        except AssessmentNotRunningError:
            # finalized concurrently (e.g. abandoned from another process):
            # stop gracefully, report the row's actual state
            db = session_factory()
            try:
                row = db.get(Assessment, assessment_id)
                status = row.status if row else AssessmentStatus.FAILED.value
                error = row.error if row else None
            finally:
                db.close()
            return _result(status, error)
        except Exception as exc:  # operational failure, not a finding
            failures += 1
            logger.warning(
                "operational failure on %s/%s: %s", assessment_id, requirement_id, exc
            )
            continue
        done_ids.add(requirement_id)
        emit(result)

    error_note = None
    final = _aggregate(session_factory, assessment_id)
    infra_abstains = final["infra_abstains"]
    if failures or infra_abstains:
        error_note = (
            f"{failures} erreur(s) opérationnelle(s), "
            f"{infra_abstains} abstention(s) pour panne LLM (llm_error/rate_limited)"
        )

    # Finalization requires MANIFEST COVERAGE: every planned requirement must
    # have a terminal finding. A partially-covered run stays RUNNING so it can
    # be resumed — completing it would silently drop the missing requirements.
    missing = [rid for rid in manifest if rid not in final["done_ids"]]
    if missing:
        note_assessment_error(
            session_factory,
            assessment_id,
            (error_note or "")
            + f" ; {len(missing)} exigence(s) sans constat : "
            + ", ".join(missing),
        )
        return _result(AssessmentStatus.RUNNING.value, error_note)

    # Cancellation re-check immediately before finalization: a cancel that
    # landed during the last requirement must win over COMPLETED.
    if _cancel_requested(session_factory, assessment_id):
        finalize_assessment(
            session_factory, assessment_id, AssessmentStatus.FAILED, error=CANCELLED_ERROR
        )
        return _result(AssessmentStatus.FAILED.value, CANCELLED_ERROR)

    # Full coverage: the COMPLETED/FAILED quality decision is owned by
    # resolve_run_status, not this runner.
    status = resolve_run_status(total, infra_abstains)
    finalize_assessment(session_factory, assessment_id, status, error=error_note)
    return _result(status.value, error_note)


def launch(session_factory: SessionFactory, assessment_id: str) -> bool:
    """Run an assessment on a daemon thread. Returns False when this process
    already has a live thread for it (local execution state only — the DB
    guards are the correctness mechanism)."""
    with _LOCK:
        existing = _THREADS.get(assessment_id)
        if existing is not None and existing.is_alive():
            return False

        def _on_progress(requirement_id: str, node: str, done: int, total: int) -> None:
            PROGRESS[assessment_id] = {
                "requirement_id": requirement_id,
                "node": node,
                "done": done,
                "total": total,
            }

        def _target() -> None:
            try:
                run_assessment(session_factory, assessment_id, on_progress=_on_progress)
            except Exception as exc:
                # keep the assessment RUNNING (resumable) — mirroring the CLI's
                # crash path; abandon is the explicit way out
                logger.exception("assessment %s crashed", assessment_id)
                try:
                    note_assessment_error(session_factory, assessment_id, str(exc))
                except Exception:
                    pass
            finally:
                with _LOCK:
                    _THREADS.pop(assessment_id, None)
                PROGRESS.pop(assessment_id, None)

        thread = threading.Thread(
            target=_target, daemon=True, name=f"assessment-{assessment_id}"
        )
        _THREADS[assessment_id] = thread
        thread.start()
        return True


def is_running_locally(assessment_id: str) -> bool:
    """True when THIS process has a live runner thread for the assessment."""
    with _LOCK:
        thread = _THREADS.get(assessment_id)
        return thread is not None and thread.is_alive()

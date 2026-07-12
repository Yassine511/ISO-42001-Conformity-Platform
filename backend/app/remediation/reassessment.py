"""Scoped effectiveness reassessment (M7a): launch protocol + evidence
validation.

The manifest is the union of the HUMAN-APPROVED effective requirement scope
(remediation_action_requirements) of the selected DONE actions of the
active plan — never the AI proposal. Holdout filtering is NEVER silent:
included_requirement_ids (∩ dev split) and excluded_holdout_ids are both
persisted and returned. A reassessment is effectiveness EVIDENCE — the human
records the verdict separately.

Crash-safe launch protocol (every window recoverable):
1. insert a PENDING launch record with a PRE-GENERATED planned_assessment_id
   (case lock, commit);
2. create_assessment(..., assessment_id=planned_assessment_id) — commits in
   its own transaction; on a crash-retry an assessment with that id already
   exists and is reconnected instead of recreated;
3. set assessment_id, REMAIN PENDING;
4. runner.launch() → LAUNCHED on True or on False (False = a live local
   thread already runs it: idempotent success); LAUNCH_FAILED only on an
   actual failure.
Reconciliation (run before every launch/list): a PENDING row whose
planned_assessment_id exists in assessments is reconnected after verifying
the org and the recorded manifest; RUNNING → idempotent re-launch,
COMPLETED/FAILED → LAUNCHED without starting another runner thread.
The launch record is append-only apart from the controlled
PENDING→LAUNCHED/LAUNCH_FAILED transition (status/error/assessment_id).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Assessment,
    RemediationAction,
    RemediationCase,
    RemediationPlan,
    RemediationReassessment,
)
from app.pipeline import runner
from app.pipeline.dev_split import DEV_REQUIREMENT_IDS
from app.pipeline.graph import AssessmentAlreadyRunningError, create_assessment
from app.remediation.service import (
    RemediationConflictError,
    RemediationInvalidError,
    RemediationNotFoundError,
    append_event,
    lock_case,
)

_DEV_SET = set(DEV_REQUIREMENT_IDS)

NO_DEV_SCOPE_FR = (
    "Le périmètre effectif des actions sélectionnées ne contient aucune "
    "exigence du jeu de développement : aucune réévaluation ne peut servir "
    "de preuve (exigences réservées au jeu de test M6). Enregistrez "
    "l'efficacité avec une preuve humaine externe (reassessment_id=null)."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _split_manifest(effective_ids: list[str]) -> tuple[list[str], list[str]]:
    included = [r for r in effective_ids if r in _DEV_SET]
    excluded = [r for r in effective_ids if r not in _DEV_SET]
    return included, excluded


def _selected_scope(actions: list[RemediationAction]) -> list[str]:
    seen: list[str] = []
    for action in actions:
        for req in action.requirements:
            if req.requirement_id not in seen:
                seen.append(req.requirement_id)
    return seen


def launch_reassessment(
    db: Session,
    session_factory,
    org_id: str,
    case_id: str,
    *,
    selected_action_ids: list[str],
    actor_label: str | None = None,
) -> RemediationReassessment:
    """Launch a scoped reassessment over the selected DONE actions of the
    active plan. Returns the launch record (LAUNCHED, or raises on guard
    conflicts with the record marked LAUNCH_FAILED)."""
    reconcile_pending(db, session_factory, org_id, case_id)

    case = lock_case(db, org_id, case_id)
    if case.status != "IN_PROGRESS":
        db.rollback()
        raise RemediationConflictError(
            f"Réévaluation impossible : statut {case.status} (IN_PROGRESS requis)."
        )
    if not selected_action_ids:
        db.rollback()
        raise RemediationInvalidError("Sélectionnez au moins une action.")
    if len(selected_action_ids) != len(set(selected_action_ids)):
        db.rollback()
        raise RemediationInvalidError("Actions sélectionnées en double.")
    plan = db.get(RemediationPlan, case.active_plan_id) if case.active_plan_id else None
    if plan is None or plan.status != "VERIFIED":
        db.rollback()
        raise RemediationConflictError("Aucun plan actif VÉRIFIÉ pour ce cas.")
    by_id = {a.id: a for a in plan.actions}
    actions: list[RemediationAction] = []
    for aid in selected_action_ids:
        action = by_id.get(aid)
        if action is None:
            db.rollback()
            raise RemediationNotFoundError(
                f"Action « {aid} » introuvable dans le plan actif."
            )
        if action.lifecycle != "DONE":
            db.rollback()
            raise RemediationInvalidError(
                f"Action « {aid} » : seule une action DONE peut être réévaluée."
            )
        actions.append(action)

    effective = _selected_scope(actions)
    included, excluded = _split_manifest(effective)
    if not included:
        db.rollback()
        raise RemediationInvalidError(NO_DEV_SCOPE_FR)

    # 1. PENDING record with the pre-generated assessment id
    record = RemediationReassessment(
        case_id=case_id,
        planned_assessment_id=str(uuid.uuid4()),
        selected_action_ids=list(selected_action_ids),
        included_requirement_ids=included,
        excluded_holdout_ids=excluded,
        status="PENDING",
        actor_label=actor_label,
    )
    db.add(record)
    db.commit()

    # 2. create (or reconnect) the assessment in its own transaction
    try:
        create_assessment(
            session_factory,
            org_id,
            included,
            assessment_id=record.planned_assessment_id,
        )
    except AssessmentAlreadyRunningError as exc:
        _finalize(db, org_id, case_id, record.id, "LAUNCH_FAILED", str(exc), actor_label)
        raise RemediationConflictError(
            "Une évaluation est déjà en cours pour cette organisation."
        )
    except Exception as exc:
        _finalize(db, org_id, case_id, record.id, "LAUNCH_FAILED", str(exc), actor_label)
        raise RemediationInvalidError(f"Création de la réévaluation impossible : {exc}")

    # 3. link, remain PENDING (crash before launch stays reconcilable)
    record = db.get(RemediationReassessment, record.id)
    record.assessment_id = record.planned_assessment_id
    db.commit()

    # 4. launch — True or False-already-running are both success
    try:
        runner.launch(session_factory, record.planned_assessment_id)
    except Exception as exc:  # pragma: no cover - defensive
        _finalize(db, org_id, case_id, record.id, "LAUNCH_FAILED", str(exc), actor_label)
        raise RemediationInvalidError(f"Démarrage de la réévaluation impossible : {exc}")
    return _finalize(db, org_id, case_id, record.id, "LAUNCHED", None, actor_label)


def _finalize(
    db: Session,
    org_id: str,
    case_id: str,
    record_id: str,
    status: str,
    error: str | None,
    actor_label: str | None,
) -> RemediationReassessment:
    """Controlled PENDING → terminal transition + audit event, under the
    case lock."""
    db.rollback()
    lock_case(db, org_id, case_id)
    record = db.get(RemediationReassessment, record_id)
    # Idempotent PENDING -> terminal compare-and-set: a concurrent reconciler
    # may have already finalized this record under the same case lock. Without
    # this guard, the second finalizer rewrites the terminal status and appends
    # a duplicate reassessment_launched event.
    if record.status != "PENDING":
        db.rollback()
        return record
    record.status = status
    record.error = error
    append_event(
        db, case_id, "reassessment_launched",
        {
            "reassessment_id": record.id,
            "planned_assessment_id": record.planned_assessment_id,
            "assessment_id": record.assessment_id,
            "selected_action_ids": record.selected_action_ids,
            "included_requirement_ids": record.included_requirement_ids,
            "excluded_holdout_ids": record.excluded_holdout_ids,
            "status": status,
        },
        actor_label,
    )
    db.commit()
    return record


def reconcile_pending(
    db: Session, session_factory, org_id: str, case_id: str
) -> None:
    """Deterministic crash recovery for PENDING launch records. Verifies the
    existing assessment belongs to this org and carries the recorded
    manifest before reconnecting it."""
    pending = db.scalars(
        select(RemediationReassessment).where(
            RemediationReassessment.case_id == case_id,
            RemediationReassessment.status == "PENDING",
        )
    ).all()
    for record in pending:
        assessment = db.get(Assessment, record.planned_assessment_id)
        if assessment is None:
            # crash BEFORE create_assessment: resume THIS record under its
            # recorded planned id and manifest — never orphan it behind a
            # fresh launch ("every crash window recoverable").
            try:
                create_assessment(
                    session_factory,
                    org_id,
                    list(record.included_requirement_ids or []),
                    assessment_id=record.planned_assessment_id,
                )
            except AssessmentAlreadyRunningError:
                continue  # transient: stays PENDING, next reconciliation resumes
            except Exception as exc:
                _finalize(db, org_id, case_id, record.id, "LAUNCH_FAILED", str(exc), None)
                continue
            assessment = db.get(Assessment, record.planned_assessment_id)
        if assessment.organization_id != org_id or sorted(
            assessment.requirement_ids or []
        ) != sorted(record.included_requirement_ids):
            _finalize(
                db, org_id, case_id, record.id, "LAUNCH_FAILED",
                "réconciliation impossible : l'évaluation retrouvée ne "
                "correspond pas au manifeste enregistré.",
                None,
            )
            continue
        db.rollback()
        lock_case(db, org_id, case_id)
        rec = db.get(RemediationReassessment, record.id)
        rec.assessment_id = record.planned_assessment_id
        db.commit()
        if assessment.status == "RUNNING":
            try:
                runner.launch(session_factory, assessment.id)  # idempotent
            except Exception as exc:  # pragma: no cover - defensive
                _finalize(db, org_id, case_id, record.id, "LAUNCH_FAILED", str(exc), None)
                continue
        # RUNNING relaunched, or already COMPLETED/FAILED: the launch happened
        _finalize(db, org_id, case_id, record.id, "LAUNCHED", None, None)


def validate_effectiveness_evidence(
    db: Session,
    case: RemediationCase,
    action: RemediationAction,
    reassessment_id: str,
) -> None:
    """A cited reassessment must actually be evidence FOR THIS ACTION:
    it belongs to the case, selected the action, its assessment COMPLETED,
    its manifest covers the action's dev-split scope, the action's own
    holdout exclusions are a SUBSET of the recorded union (not equality —
    the union spans all selected actions), and the recorded union matches a
    recomputation over the selected actions (integrity)."""
    record = db.get(RemediationReassessment, reassessment_id)
    if record is None or record.case_id != case.id:
        db.rollback()
        raise RemediationNotFoundError("Réévaluation introuvable pour ce cas.")
    if action.id not in (record.selected_action_ids or []):
        db.rollback()
        raise RemediationInvalidError(
            "Cette réévaluation ne portait pas sur cette action."
        )
    if record.assessment_id is None:
        db.rollback()
        raise RemediationInvalidError("Réévaluation jamais lancée (aucune évaluation liée).")
    assessment = db.get(Assessment, record.assessment_id)
    if assessment is None or assessment.status != "COMPLETED":
        db.rollback()
        raise RemediationInvalidError(
            "L'évaluation liée n'est pas terminée (COMPLETED requis) : elle ne "
            "peut pas servir de preuve."
        )
    effective_ids = [r.requirement_id for r in action.requirements]
    dev_part = [r for r in effective_ids if r in _DEV_SET]
    holdout_part = [r for r in effective_ids if r not in _DEV_SET]
    if not dev_part:
        db.rollback()
        raise RemediationInvalidError(NO_DEV_SCOPE_FR)
    manifest = set(assessment.requirement_ids or [])
    missing = [r for r in dev_part if r not in manifest]
    if missing:
        db.rollback()
        raise RemediationInvalidError(
            "L'évaluation liée ne couvre pas le périmètre de l'action : "
            + ", ".join(missing)
        )
    recorded_excluded = set(record.excluded_holdout_ids or [])
    stray = [r for r in holdout_part if r not in recorded_excluded]
    if stray:
        db.rollback()
        raise RemediationInvalidError(
            "Incohérence d'exclusions : exigences hors jeu de développement "
            "non enregistrées lors du lancement : " + ", ".join(stray)
        )
    # integrity: recompute the union over the selected actions
    selected = db.scalars(
        select(RemediationAction).where(
            RemediationAction.id.in_(record.selected_action_ids or [])
        )
    ).all()
    recomputed_excluded = {
        req.requirement_id
        for a in selected
        for req in a.requirements
        if req.requirement_id not in _DEV_SET
    }
    if recomputed_excluded != recorded_excluded:
        db.rollback()
        raise RemediationInvalidError(
            "Intégrité compromise : les exclusions enregistrées au lancement "
            "ne correspondent plus au périmètre effectif des actions "
            "sélectionnées."
        )

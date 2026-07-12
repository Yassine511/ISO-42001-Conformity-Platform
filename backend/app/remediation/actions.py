"""Per-action human review, lifecycle and effectiveness (M7a).

ACTIVE-PLAN ACTION AUTHORITY (invariant, enforced by every entry point
here): an action is operable only when its plan is the case's
active_plan_id AND that plan is VERIFIED. Actions of ABSTAINED, SUPERSEDED,
inactive or foreign-case plans are immutable historical records — their
lifecycle is never rewritten.

Review windows: initial review only from PROPOSED; re-review only while
APPROVED (before execution starts). approve snapshots the AI values into
the effective columns; edit stores the human text; reject clears the
effective fields AND the effective requirement rows (prior values preserved
in the event payload) and terminates the lifecycle at REJECTED. `priority`
is human-assigned and mandatory on approve/edit.

Effective requirement scope (remediation_action_requirements) is written
ONLY here: approve snapshots ai_impacted_requirement_ids; edit may supply
human ids (non-empty, duplicate-free, validated against the live KB and
snapshotted — recorded as an override). It feeds the effectiveness
reassessment manifest and M7b's RemediationContext later.

Two independent tracking dimensions (spec §8): lifecycle
(PROPOSED→APPROVED→IN_PROGRESS→DONE, REJECTED/CANCELLED terminal) and
effectiveness (recordable only on DONE, re-recordable — events keep
history). A reassessment may be cited as effectiveness EVIDENCE (validated
in reassessment.py), never as proof.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    RemediationAction,
    RemediationActionRequirement,
    RemediationCase,
    RemediationPlan,
)
from app.remediation.service import (
    RemediationConflictError,
    RemediationInvalidError,
    RemediationNotFoundError,
    append_event,
    lock_case,
)
from app.services.retrieval import load_kb

PRIORITIES = ("haute", "normale", "basse")

LIFECYCLE_TRANSITIONS = {
    "APPROVED": ("IN_PROGRESS", "CANCELLED"),
    "IN_PROGRESS": ("DONE", "CANCELLED"),
}

INERT_ACTION_FR = (
    "Cette action n'appartient pas au plan actif VÉRIFIÉ du cas : les actions "
    "des plans remplacés ou en abstention sont des archives immuables."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _operable_action(
    db: Session, case: RemediationCase, action_id: str
) -> RemediationAction:
    """Resolve an action under the active-plan authority invariant. The case
    lock is already held by the caller. A CLOSED case is immutable except
    through reopen; a PLANNING case is mid-draft and its plan snapshot must
    stay frozen (see below)."""
    if case.status == "CLOSED":
        db.rollback()
        raise RemediationConflictError(
            "Cas clôturé : rouvrez-le avant toute opération sur ses actions."
        )
    if case.status == "PLANNING":
        # A draft releases the case lock during its LLM phase, then phase 3
        # supersedes the active plan after re-checking only the planning
        # token/lease. Mutating an active-plan action in that window would let
        # a just-approved (or lifecycle-advanced) action be silently superseded
        # into inert history. Reject the mutation immediately (409) so the
        # plan snapshot stays stable for the whole draft.
        db.rollback()
        raise RemediationConflictError(
            "Rédaction de plan en cours : les actions ne peuvent pas être "
            "modifiées tant que le plan n'est pas finalisé."
        )
    action = db.get(RemediationAction, action_id)
    if action is None:
        db.rollback()
        raise RemediationNotFoundError("Action introuvable pour ce cas.")
    plan = db.get(RemediationPlan, action.plan_id)
    if plan.case_id != case.id:
        db.rollback()
        raise RemediationNotFoundError("Action introuvable pour ce cas.")
    if plan.id != case.active_plan_id or plan.status != "VERIFIED":
        db.rollback()
        raise RemediationConflictError(INERT_ACTION_FR)
    return action


def _effective_snapshot(action: RemediationAction) -> dict:
    return {
        "review_status": action.review_status,
        "review_action": action.review_action,
        "description": action.description,
        "rationale": action.rationale,
        "owner_role": action.owner_role,
        "success_criterion": action.success_criterion,
        "priority": action.priority,
        "lifecycle": action.lifecycle,
        "effective_requirement_ids": [r.requirement_id for r in action.requirements],
    }


def review_action(
    db: Session,
    org_id: str,
    case_id: str,
    action_id: str,
    *,
    action: str,  # 'approve' | 'edit' | 'reject'
    description: str | None = None,
    rationale: str | None = None,
    owner_role: str | None = None,
    success_criterion: str | None = None,
    priority: str | None = None,
    impacted_requirement_ids: list[str] | None = None,
    review_note: str | None = None,
    reviewer_label: str | None = None,
) -> RemediationAction:
    """Record the human decision on one action. Writes ONLY the review
    projection + effective requirement rows + events — AI columns are never
    touched. Commits."""
    case = lock_case(db, org_id, case_id)
    row = _operable_action(db, case, action_id)

    # review windows
    if row.review_status == "PENDING":
        if row.lifecycle != "PROPOSED":  # defensive: CHECK makes this a 500 otherwise
            db.rollback()
            raise RemediationConflictError("État d'action incohérent.")
    elif row.lifecycle != "APPROVED":
        db.rollback()
        raise RemediationConflictError(
            "Re-revue impossible : une action ne peut être re-revue que tant "
            f"qu'elle est APPROVED (statut actuel : {row.lifecycle})."
        )

    if action not in ("approve", "edit", "reject"):
        db.rollback()
        raise RemediationInvalidError("Action de revue inconnue.")

    before = _effective_snapshot(row)
    requirement_override = False
    effective_ids: list[str] = []

    if action == "reject":
        row.review_action = "reject"
        row.description = None
        row.rationale = None
        row.owner_role = None
        row.success_criterion = None
        row.priority = None
        row.lifecycle = "REJECTED"
        for req in list(row.requirements):
            db.delete(req)
    else:
        if not priority or priority not in PRIORITIES:
            db.rollback()
            raise RemediationInvalidError(
                "La priorité (haute, normale ou basse) est obligatoire pour "
                "approuver ou modifier une action."
            )
        if action == "approve":
            row.description = row.ai_description
            row.rationale = row.ai_rationale
            row.owner_role = row.ai_owner_role
            row.success_criterion = row.ai_success_criterion
        else:  # edit: human text wins; omitted fields keep the AI values
            row.description = (description or "").strip() or row.ai_description
            row.rationale = (rationale or "").strip() or row.ai_rationale
            row.owner_role = (owner_role or "").strip() or row.ai_owner_role
            row.success_criterion = (
                (success_criterion or "").strip() or row.ai_success_criterion
            )
        # Effective requirement scope: an OMITTED list never silently reverts
        # a previous human decision — on re-review it preserves the current
        # effective rows; only the initial review defaults to the AI proposal.
        current_ids = [r.requirement_id for r in row.requirements]
        if impacted_requirement_ids is not None:
            effective_ids = impacted_requirement_ids
        elif current_ids:
            effective_ids = current_ids
        else:
            effective_ids = list(row.ai_impacted_requirement_ids)
        requirement_override = sorted(effective_ids) != sorted(
            row.ai_impacted_requirement_ids
        )
        # validate + snapshot the effective scope against the live KB (the
        # human owns an override, but it must still name real requirements)
        if not effective_ids:
            db.rollback()
            raise RemediationInvalidError(
                "Le périmètre d'exigences effectif ne peut pas être vide."
            )
        if len(effective_ids) != len(set(effective_ids)):
            db.rollback()
            raise RemediationInvalidError(
                "Le périmètre d'exigences effectif contient des doublons."
            )
        kb = load_kb()
        unknown = [r for r in effective_ids if r not in kb["by_id"]]
        if unknown:
            db.rollback()
            raise RemediationInvalidError(
                "Exigence(s) inconnue(s) dans la base ISO 42001 : "
                + ", ".join(unknown)
            )
        row.priority = priority
        row.review_action = action
        row.lifecycle = "APPROVED"

    # complete the projection BEFORE any flush: a partial UPDATE would
    # violate ck_remediation_actions_review_coherence
    row.review_status = "CONFIRMED"
    row.review_note = review_note
    row.reviewer_label = reviewer_label
    row.reviewed_at = _now()
    row.review_count += 1
    if action != "reject":
        # re-review replaces the effective scope
        for req in list(row.requirements):
            db.delete(req)
        db.flush()
        for rid in effective_ids:
            entry = kb["by_id"][rid]
            db.add(
                RemediationActionRequirement(
                    action_id=row.id,
                    requirement_id=rid,
                    requirement_fr=entry["requirement_fr"],
                    domain=entry.get("domain"),
                )
            )
    db.flush()
    db.refresh(row)

    append_event(
        db, case.id, "action_reviewed",
        {
            "action_id": row.id,
            "review_action": action,
            "before": before,
            "after": _effective_snapshot(row),
            "effective_requirement_ids": effective_ids,
            "requirement_override": requirement_override,
        },
        reviewer_label,
    )
    if case.status == "PLAN_READY":  # first review starts execution
        case.status = "IN_PROGRESS"
    case.updated_at = _now()
    db.commit()
    return row


def change_lifecycle(
    db: Session,
    org_id: str,
    case_id: str,
    action_id: str,
    *,
    lifecycle: str,
    actor_label: str | None = None,
) -> RemediationAction:
    """Validated lifecycle transition (PROPOSED/REJECTED are review-owned:
    APPROVED→IN_PROGRESS→DONE, APPROVED/IN_PROGRESS→CANCELLED). Commits."""
    case = lock_case(db, org_id, case_id)
    row = _operable_action(db, case, action_id)
    allowed = LIFECYCLE_TRANSITIONS.get(row.lifecycle, ())
    if lifecycle not in allowed:
        db.rollback()
        raise RemediationConflictError(
            f"Transition invalide : {row.lifecycle} → {lifecycle}."
        )
    before = row.lifecycle
    row.lifecycle = lifecycle
    append_event(
        db, case.id, "lifecycle_changed",
        {"action_id": row.id, "before": before, "after": lifecycle},
        actor_label,
    )
    case.updated_at = _now()
    db.commit()
    return row


def record_effectiveness(
    db: Session,
    org_id: str,
    case_id: str,
    action_id: str,
    *,
    effectiveness: str,
    note: str,
    reassessment_id: str | None = None,
    actor_label: str | None = None,
) -> RemediationAction:
    """Record the human effectiveness verdict on a DONE action. A cited
    reassessment is validated as EVIDENCE (reassessment.py) — never proof.
    Re-recordable; events keep history. Commits."""
    case = lock_case(db, org_id, case_id)
    row = _operable_action(db, case, action_id)
    if row.lifecycle != "DONE":
        db.rollback()
        raise RemediationConflictError(
            "L'efficacité ne peut être enregistrée que sur une action DONE."
        )
    if effectiveness not in ("EFFECTIVE", "PARTIALLY_EFFECTIVE", "INEFFECTIVE"):
        db.rollback()
        raise RemediationInvalidError("Verdict d'efficacité inconnu.")
    if not (note or "").strip():
        db.rollback()
        raise RemediationInvalidError(
            "L'enregistrement de l'efficacité exige une note (preuve humaine)."
        )
    if reassessment_id is not None:
        from app.remediation.reassessment import validate_effectiveness_evidence

        validate_effectiveness_evidence(db, case, row, reassessment_id)

    before = {
        "effectiveness": row.effectiveness,
        "effectiveness_note": row.effectiveness_note,
    }
    row.effectiveness = effectiveness
    row.effectiveness_note = note.strip()
    row.effectiveness_recorded_at = _now()
    append_event(
        db, case.id, "effectiveness_recorded",
        {
            "action_id": row.id,
            "before": before,
            "after": {"effectiveness": effectiveness, "effectiveness_note": note.strip()},
            "reassessment_id": reassessment_id,
        },
        actor_label,
    )
    case.updated_at = _now()
    db.commit()
    return row

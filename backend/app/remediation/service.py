"""Remediation case service (M7a): creation, linking, events, triage
approval/reopen, closure/reopen.

Locking invariant (all mutations): lock the CASE row first, then any
plan/action/finding rows it needs — findings in deterministic id order.
Stated exception: case creation locks the finding first, because the case
row does not exist yet. No LLM/network call ever runs while these locks are
held (triage/planner draft flows snapshot under the lock, release, call the
provider, then relock and revalidate).

Eligibility doctrine: a finding is remediation-eligible only when
review_status='CONFIRMED' AND human_verdict is a GAP verdict
(partial/non_compliant/missing) — CONFIRMED alone includes compliant
findings. One ACTIVE (non-CLOSED) case per finding, enforced under the
finding row lock at creation, link and reopen (a cross-table invariant the
DB cannot express).
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Finding,
    Organization,
    RemediationCase,
    RemediationCaseFinding,
    RemediationEvent,
    RemediationPlan,
)
from app.remediation.events import PAYLOAD_VERSION, validate_payload

ELIGIBLE_VERDICTS = ("partial", "non_compliant", "missing")

NOT_ELIGIBLE_FR = (
    "Seul un constat CONFIRMÉ avec un verdict d'écart (partial, non_compliant "
    "ou missing) peut ouvrir ou rejoindre un cas de remédiation."
)
LINKS_FROZEN_FR = (
    "Les constats liés ne peuvent être modifiés qu'au stade TRIAGE : rouvrez "
    "d'abord le triage."
)


class RemediationNotFoundError(LookupError):
    """Mapped to 404 by the router."""


class RemediationConflictError(RuntimeError):
    """Mapped to 409 by the router."""


class RemediationInvalidError(ValueError):
    """Mapped to 422 by the router."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def append_event(
    db: Session,
    case_id: str,
    event_type: str,
    payload: dict,
    actor_label: str | None = None,
) -> RemediationEvent:
    """Append one audit event. The CALLER must hold the case row lock —
    sequence assignment is only race-free under it."""
    payload = validate_payload(event_type, payload)
    # SessionLocal runs with autoflush=False: a previous append_event in the
    # same transaction would be invisible to the SELECT below and both events
    # would claim the same sequence (caught by the live E2E, not SQLite tests
    # whose sessions autoflush).
    db.flush()
    last = db.scalar(
        select(RemediationEvent.sequence)
        .where(RemediationEvent.case_id == case_id)
        .order_by(RemediationEvent.sequence.desc())
        .limit(1)
    )
    event = RemediationEvent(
        case_id=case_id,
        sequence=(last or 0) + 1,
        event_type=event_type,
        payload=payload,
        payload_version=PAYLOAD_VERSION,
        actor_label=actor_label,
    )
    db.add(event)
    return event


def get_case(db: Session, org_id: str, case_id: str) -> RemediationCase:
    case = db.get(RemediationCase, case_id)
    if case is None or case.organization_id != org_id:
        raise RemediationNotFoundError("Cas de remédiation introuvable pour cette organisation.")
    return case


def lock_case(db: Session, org_id: str, case_id: str) -> RemediationCase:
    """Case row lock (the aggregate lock). 404 before locking semantics are
    preserved by re-checking the org after the lock."""
    case = db.get(RemediationCase, case_id, with_for_update=True)
    if case is None or case.organization_id != org_id:
        db.rollback()
        raise RemediationNotFoundError("Cas de remédiation introuvable pour cette organisation.")
    return case


def finding_snapshot(link: RemediationCaseFinding) -> dict:
    """Event/input snapshot of one link row (the case's recorded basis)."""
    return {
        "finding_id": link.finding_id,
        "is_primary": link.is_primary,
        "link_source": link.link_source,
        "finding_review_count": link.finding_review_count,
        "finding_human_verdict": link.finding_human_verdict,
        "finding_human_rationale": link.finding_human_rationale,
        "finding_requirement_id": link.finding_requirement_id,
        "finding_requirement_fr": link.finding_requirement_fr,
        "finding_domain": link.finding_domain,
    }


def _check_eligible(finding: Finding, org_id: str) -> None:
    if finding.assessment.organization_id != org_id:
        raise RemediationNotFoundError("Constat introuvable pour cette organisation.")
    if finding.review_status != "CONFIRMED" or finding.human_verdict not in ELIGIBLE_VERDICTS:
        raise RemediationInvalidError(NOT_ELIGIBLE_FR)


def _assert_no_other_active_case(
    db: Session, finding_id: str, exclude_case_id: str | None = None
) -> None:
    """One active case per finding. Caller holds the finding row lock."""
    query = (
        select(RemediationCase.id)
        .join(
            RemediationCaseFinding,
            RemediationCaseFinding.case_id == RemediationCase.id,
        )
        .where(
            RemediationCaseFinding.finding_id == finding_id,
            RemediationCase.status != "CLOSED",
        )
    )
    if exclude_case_id is not None:
        query = query.where(RemediationCase.id != exclude_case_id)
    other = db.scalar(query.limit(1))
    if other is not None:
        raise RemediationConflictError(
            f"Ce constat appartient déjà à un cas de remédiation actif ({other})."
        )


def _link_row(
    finding: Finding, case_id: str, *, is_primary: bool, link_source: str,
    link_note: str | None, linker_label: str | None,
) -> RemediationCaseFinding:
    return RemediationCaseFinding(
        case_id=case_id,
        finding_id=finding.id,
        is_primary=is_primary,
        link_source=link_source,
        link_note=link_note,
        linker_label=linker_label,
        finding_review_count=finding.review_count,
        finding_human_verdict=finding.human_verdict,
        finding_human_rationale=finding.human_rationale,
        finding_requirement_id=finding.requirement_id,
        finding_requirement_fr=finding.requirement_fr,
        finding_domain=finding.domain,
    )


def create_case(
    db: Session,
    org_id: str,
    finding_id: str,
    *,
    title: str | None = None,
    link_note: str | None = None,
    actor_label: str | None = None,
) -> RemediationCase:
    """Create a case from one eligible finding (primary link). Commits.

    Lock-order exception (stated in the module doc): the finding row is
    locked first — the case row does not exist yet.
    """
    if db.get(Organization, org_id) is None:
        raise RemediationNotFoundError("Organisation introuvable.")
    finding = db.get(Finding, finding_id, with_for_update=True)
    if finding is None:
        raise RemediationNotFoundError("Constat introuvable pour cette organisation.")
    _check_eligible(finding, org_id)
    _assert_no_other_active_case(db, finding_id)

    case_title = (title or "").strip() or (
        f"Remédiation {finding.requirement_id} — {finding.human_verdict}"
    )
    case = RemediationCase(
        organization_id=org_id, title=case_title[:300], status="TRIAGE"
    )
    db.add(case)
    db.flush()
    link = _link_row(
        finding,
        case.id,
        is_primary=True,
        link_source="creation",
        link_note=link_note,
        linker_label=actor_label,
    )
    db.add(link)
    db.flush()
    append_event(
        db, case.id, "case_created",
        {"finding_id": finding_id, "title": case.title}, actor_label,
    )
    append_event(
        db, case.id, "finding_linked",
        {
            "finding_id": finding_id,
            "link_source": "creation",
            "is_primary": True,
            "snapshot": finding_snapshot(link),
        },
        actor_label,
    )
    db.commit()
    return case


def link_finding(
    db: Session,
    org_id: str,
    case_id: str,
    finding_id: str,
    *,
    decision: str,  # 'link' | 'reject'
    link_source: str = "manual",  # 'search_suggested' | 'manual'
    link_note: str | None = None,
    actor_label: str | None = None,
) -> RemediationCase:
    """Link a finding to (or reject a suggestion for) a TRIAGE case. Commits.
    Every successful link increments evidence_revision (stale-input
    protection for in-flight triage drafts)."""
    case = lock_case(db, org_id, case_id)
    if case.status != "TRIAGE":
        db.rollback()
        raise RemediationConflictError(LINKS_FROZEN_FR)

    if decision == "reject":
        # provenance only: the human saw the suggestion and dismissed it
        append_event(
            db, case.id, "finding_link_rejected",
            {"finding_id": finding_id, "note": link_note}, actor_label,
        )
        case.updated_at = _now()
        db.commit()
        return case

    finding = db.get(Finding, finding_id, with_for_update=True)
    if finding is None:
        db.rollback()
        raise RemediationNotFoundError("Constat introuvable pour cette organisation.")
    _check_eligible(finding, org_id)
    already = db.scalar(
        select(RemediationCaseFinding.id).where(
            RemediationCaseFinding.case_id == case_id,
            RemediationCaseFinding.finding_id == finding_id,
        )
    )
    if already is not None:
        db.rollback()
        raise RemediationConflictError("Ce constat est déjà lié à ce cas.")
    _assert_no_other_active_case(db, finding_id)

    link = _link_row(
        finding,
        case.id,
        is_primary=False,
        link_source=link_source,
        link_note=link_note,
        linker_label=actor_label,
    )
    db.add(link)
    db.flush()
    case.evidence_revision += 1
    case.updated_at = _now()
    append_event(
        db, case.id, "finding_linked",
        {
            "finding_id": finding_id,
            "link_source": link_source,
            "is_primary": False,
            "snapshot": finding_snapshot(link),
        },
        actor_label,
    )
    db.commit()
    return case


def unlink_finding(
    db: Session,
    org_id: str,
    case_id: str,
    finding_id: str,
    *,
    actor_label: str | None = None,
) -> RemediationCase:
    """Remove a non-primary link from a TRIAGE case. Commits."""
    case = lock_case(db, org_id, case_id)
    if case.status != "TRIAGE":
        db.rollback()
        raise RemediationConflictError(LINKS_FROZEN_FR)
    link = db.scalar(
        select(RemediationCaseFinding).where(
            RemediationCaseFinding.case_id == case_id,
            RemediationCaseFinding.finding_id == finding_id,
        )
    )
    if link is None:
        db.rollback()
        raise RemediationNotFoundError("Ce constat n'est pas lié à ce cas.")
    if link.is_primary:
        db.rollback()
        raise RemediationInvalidError(
            "Le constat principal du cas ne peut pas être délié."
        )
    snapshot = finding_snapshot(link)
    db.delete(link)
    case.evidence_revision += 1
    case.updated_at = _now()
    append_event(
        db, case.id, "finding_unlinked",
        {"finding_id": finding_id, "snapshot": snapshot}, actor_label,
    )
    db.commit()
    return case


def link_suggestions(db: Session, org_id: str, case_id: str) -> list[dict]:
    """Eligible, unlinked CONFIRMED gap findings of the org, same-domain
    first. Deterministic SQL — the human links or rejects; both decisions are
    provenance-logged."""
    case = get_case(db, org_id, case_id)
    linked_ids = {l.finding_id for l in case.finding_links}
    domains = {l.finding_domain for l in case.finding_links if l.finding_domain}
    from app.models import Assessment  # local import to avoid cycle noise

    rows = db.scalars(
        select(Finding)
        .join(Assessment, Finding.assessment_id == Assessment.id)
        .where(
            Assessment.organization_id == org_id,
            Finding.review_status == "CONFIRMED",
            Finding.human_verdict.in_(ELIGIBLE_VERDICTS),
        )
        .order_by(Finding.reviewed_at.desc())
    ).all()
    suggestions = []
    for f in rows:
        if f.id in linked_ids:
            continue
        suggestions.append(
            {
                "finding_id": f.id,
                "assessment_id": f.assessment_id,
                "requirement_id": f.requirement_id,
                "requirement_fr": f.requirement_fr,
                "domain": f.domain,
                "human_verdict": f.human_verdict,
                "human_rationale": f.human_rationale,
                "same_domain": bool(f.domain and f.domain in domains),
            }
        )
    suggestions.sort(key=lambda s: (not s["same_domain"],))
    return suggestions


# ------------------------------------------------------------ triage approval


def approve_triage(
    db: Session,
    org_id: str,
    case_id: str,
    triage_draft_id: str,
    *,
    classification: str | None = None,
    correction_note: str | None = None,
    scope: str | None = None,
    scope_rationale: str | None = None,
    reviewer_label: str | None = None,
) -> RemediationCase:
    """Approve one EXPLICIT triage draft (never 'latest'). Omitted fields
    accept the AI draft; provided fields override. An ABSTAINED draft has no
    AI values to accept — all fields are then required. Commits."""
    from app.models import RemediationTriageDraft

    case = lock_case(db, org_id, case_id)
    if case.status != "TRIAGE":
        db.rollback()
        raise RemediationConflictError(
            f"Approbation impossible : statut {case.status} (TRIAGE requis)."
        )
    draft = db.get(RemediationTriageDraft, triage_draft_id)
    if draft is None or draft.case_id != case_id:
        db.rollback()
        raise RemediationNotFoundError("Proposition de triage introuvable pour ce cas.")
    if draft.input_evidence_revision != case.evidence_revision:
        db.rollback()
        raise RemediationConflictError(
            "Cette proposition de triage est périmée : les constats liés ont "
            "changé depuis sa rédaction. Relancez le triage."
        )

    effective = {
        "classification": classification or draft.ai_classification,
        "correction_note": (
            correction_note if correction_note is not None else draft.ai_correction_note
        ),
        "scope": scope or draft.ai_scope,
        "scope_rationale": scope_rationale or draft.ai_scope_rationale,
    }
    # A VERIFIED draft always carries a correction note; on an ABSTAINED
    # draft the human supplies EVERY field, correction note included.
    required = ("classification", "correction_note", "scope", "scope_rationale")
    missing = [k for k in required if not effective[k]]
    if missing:
        db.rollback()
        raise RemediationInvalidError(
            "Champs requis manquants (proposition en abstention — fournissez "
            "votre triage) : " + ", ".join(missing)
        )
    overridden = [
        k
        for k, ai in (
            ("classification", draft.ai_classification),
            ("correction_note", draft.ai_correction_note),
            ("scope", draft.ai_scope),
            ("scope_rationale", draft.ai_scope_rationale),
        )
        if effective[k] != ai
    ]

    case.classification = effective["classification"]
    case.correction_note = effective["correction_note"]
    case.scope = effective["scope"]
    case.scope_rationale = effective["scope_rationale"]
    case.triage_approved_at = _now()
    case.triage_reviewer_label = reviewer_label
    case.approved_triage_draft_id = draft.id
    case.status = "TRIAGE_APPROVED"
    case.updated_at = _now()
    append_event(
        db, case.id, "triage_approved",
        {
            "triage_draft_id": draft.id,
            "after": effective,
            "overridden_fields": overridden,
        },
        reviewer_label,
    )
    db.commit()
    return case


def _active_plan(db: Session, case: RemediationCase) -> RemediationPlan | None:
    if case.active_plan_id is None:
        return None
    return db.get(RemediationPlan, case.active_plan_id)


def _all_actions_proposed(plan: RemediationPlan | None) -> bool:
    return plan is None or all(a.lifecycle == "PROPOSED" for a in plan.actions)


def reopen_triage(
    db: Session,
    org_id: str,
    case_id: str,
    *,
    actor_label: str | None = None,
) -> RemediationCase:
    """Reopen triage: allowed from TRIAGE_APPROVED/PLAN_READY while every
    action of the active plan is still PROPOSED. Supersedes the active plan
    (VERIFIED or ABSTAINED), clears the human triage projection (values
    preserved in the event) and bumps evidence_revision. Commits."""
    case = lock_case(db, org_id, case_id)
    if case.status not in ("TRIAGE_APPROVED", "PLAN_READY"):
        db.rollback()
        raise RemediationConflictError(
            f"Réouverture du triage impossible : statut {case.status}."
        )
    plan = _active_plan(db, case)
    if not _all_actions_proposed(plan):
        db.rollback()
        raise RemediationConflictError(
            "Réouverture du triage impossible : des actions du plan actif ont "
            "déjà été traitées. Clôturez ou annulez ce travail, ou ouvrez un "
            "nouveau cas."
        )

    before = {
        "classification": case.classification,
        "correction_note": case.correction_note,
        "scope": case.scope,
        "scope_rationale": case.scope_rationale,
        "triage_approved_at": (
            case.triage_approved_at.isoformat() if case.triage_approved_at else None
        ),
        "triage_reviewer_label": case.triage_reviewer_label,
        "approved_triage_draft_id": case.approved_triage_draft_id,
    }
    superseded_plan_id = None
    if plan is not None:
        plan.status = "SUPERSEDED"
        plan.superseded_at = _now()
        # superseded_by_plan_id stays NULL: triage-reopen supersession
        superseded_plan_id = plan.id
        append_event(
            db, case.id, "plan_superseded",
            {"plan_id": plan.id, "superseded_by_plan_id": None, "cause": "triage_reopen"},
            actor_label,
        )
    case.active_plan_id = None
    case.classification = None
    case.correction_note = None
    case.scope = None
    case.scope_rationale = None
    case.triage_approved_at = None
    case.triage_reviewer_label = None
    case.approved_triage_draft_id = None
    case.evidence_revision += 1
    case.status = "TRIAGE"
    case.updated_at = _now()
    append_event(
        db, case.id, "triage_reopened",
        {"before": before, "superseded_plan_id": superseded_plan_id},
        actor_label,
    )
    db.commit()
    return case


# ------------------------------------------------------------ close / reopen

OPEN_LIFECYCLES = ("PROPOSED", "APPROVED", "IN_PROGRESS")


def close_case(
    db: Session,
    org_id: str,
    case_id: str,
    *,
    close_note: str,
    actor_label: str | None = None,
) -> RemediationCase:
    """Close: allowed from TRIAGE_APPROVED/PLAN_READY/IN_PROGRESS with no
    ACTIVE-PLAN action still open (superseded plans' actions are inert
    historical records and never counted). Commits."""
    case = lock_case(db, org_id, case_id)
    if case.status not in ("TRIAGE_APPROVED", "PLAN_READY", "IN_PROGRESS"):
        db.rollback()
        raise RemediationConflictError(
            f"Clôture impossible : statut {case.status}."
        )
    if not (close_note or "").strip():
        db.rollback()
        raise RemediationInvalidError("La clôture exige une note (close_note).")
    plan = _active_plan(db, case)
    if plan is not None and plan.status == "VERIFIED":
        open_actions = [a.id for a in plan.actions if a.lifecycle in OPEN_LIFECYCLES]
        if open_actions:
            db.rollback()
            raise RemediationConflictError(
                "Clôture impossible : des actions du plan actif sont encore "
                "ouvertes (rejetez, terminez ou annulez-les d'abord)."
            )
    from_status = case.status
    case.status = "CLOSED"
    case.closed_at = _now()
    case.close_note = close_note.strip()
    case.updated_at = _now()
    append_event(
        db, case.id, "case_closed",
        {"close_note": case.close_note, "from_status": from_status}, actor_label,
    )
    db.commit()
    return case


def reopen_case(
    db: Session,
    org_id: str,
    case_id: str,
    *,
    actor_label: str | None = None,
) -> RemediationCase:
    """Reopen a CLOSED case. Re-locks every linked finding (deterministic id
    order, case lock already held) and rejects when any of them now belongs
    to another active case — reopening must never violate
    one-active-case-per-finding. Restores the state implied by data. Commits."""
    case = lock_case(db, org_id, case_id)
    if case.status != "CLOSED":
        db.rollback()
        raise RemediationConflictError(
            f"Réouverture impossible : statut {case.status} (CLOSED requis)."
        )
    finding_ids = sorted(l.finding_id for l in case.finding_links)
    for fid in finding_ids:  # case first, findings second, id order
        db.get(Finding, fid, with_for_update=True)
        _assert_no_other_active_case_or_rollback(db, fid, case.id)

    before_note, before_at = case.close_note, case.closed_at
    plan = _active_plan(db, case)
    if plan is not None and plan.status == "VERIFIED" and any(
        a.lifecycle != "PROPOSED" for a in plan.actions
    ):
        restored = "IN_PROGRESS"
    elif case.active_plan_id is not None:
        restored = "PLAN_READY"
    elif case.triage_approved_at is not None:
        restored = "TRIAGE_APPROVED"
    else:
        restored = "TRIAGE"
    case.status = restored
    case.closed_at = None
    case.close_note = None
    case.updated_at = _now()
    append_event(
        db, case.id, "case_reopened",
        {
            "previous_close_note": before_note,
            "previous_closed_at": before_at.isoformat() if before_at else "",
            "restored_status": restored,
        },
        actor_label,
    )
    db.commit()
    return case


def _assert_no_other_active_case_or_rollback(
    db: Session, finding_id: str, exclude_case_id: str
) -> None:
    try:
        _assert_no_other_active_case(db, finding_id, exclude_case_id)
    except RemediationConflictError:
        db.rollback()
        raise

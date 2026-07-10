"""M7a remediation case API: creation from a confirmed gap finding, linking,
triage draft/approve/reopen, close/reopen.

Org scoping is structural (assessments.py pattern): every route nests under
/organizations/{org_id}/... and the service re-checks the resource chain.
Service exceptions map: NotFound -> 404, Conflict -> 409, Invalid -> 422.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import Organization, RemediationCase
from app.remediation import planner, service, triage
from app.remediation.service import (
    RemediationConflictError,
    RemediationInvalidError,
    RemediationNotFoundError,
)
from app.schemas import (
    RemediationActorBody,
    RemediationCaseCreate,
    RemediationCaseFindingOut,
    RemediationCaseOut,
    RemediationCloseBody,
    RemediationEventOut,
    RemediationLinkDecision,
    RemediationActionOut,
    RemediationLinkSuggestionOut,
    RemediationPlanOut,
    RemediationTriageApprove,
    RemediationTriageDraftOut,
)

router = APIRouter(prefix="/api", tags=["remediation"])


def get_session_factory():
    """Session factory for the planner's short heartbeat transactions
    (overridden in tests to share the request database)."""
    return SessionLocal


def _get_org(db: Session, org_id: str) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "Organisation introuvable.")
    return org


def _run(fn, *args, **kwargs):
    """Map service exceptions to HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except RemediationNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except RemediationConflictError as exc:
        raise HTTPException(409, str(exc))
    except RemediationInvalidError as exc:
        raise HTTPException(422, str(exc))


def _case_payload(db: Session, case: RemediationCase, *, detail: bool = False) -> dict:
    base = RemediationCaseOut.model_validate(case).model_dump()
    base["finding_links"] = [
        RemediationCaseFindingOut.model_validate(l).model_dump()
        for l in sorted(case.finding_links, key=lambda l: l.created_at)
    ]
    if detail:
        base["triage_drafts"] = [
            RemediationTriageDraftOut.model_validate(d).model_dump()
            for d in case.triage_drafts
        ]
        base["plans"] = [_plan_payload(p) for p in case.plans]
        base["events"] = [
            RemediationEventOut.model_validate(e).model_dump() for e in case.events
        ]
    return base


def _plan_payload(plan) -> dict:
    body = RemediationPlanOut.model_validate(plan).model_dump()
    body["actions"] = [
        RemediationActionOut.model_validate(a).model_dump() for a in plan.actions
    ]
    return body


@router.post("/organizations/{org_id}/remediation-cases", status_code=201)
def create_case(
    org_id: str, body: RemediationCaseCreate, db: Session = Depends(get_db)
):
    """Create a case from one eligible finding, then draft the triage
    synchronously. A retrieval failure still returns 201 with an ABSTAINED
    retrieval_error draft — the case exists and is auditable."""
    _get_org(db, org_id)
    case = _run(
        service.create_case,
        db,
        org_id,
        body.finding_id,
        title=body.title,
        link_note=body.link_note,
        actor_label=body.actor_label,
    )
    _run(triage.draft_triage, db, org_id, case.id, actor_label=body.actor_label)
    db.expire_all()
    case = service.get_case(db, org_id, case.id)
    return _case_payload(db, case, detail=True)


@router.get("/organizations/{org_id}/remediation-cases")
def list_cases(org_id: str, db: Session = Depends(get_db)):
    _get_org(db, org_id)
    cases = db.scalars(
        select(RemediationCase)
        .where(RemediationCase.organization_id == org_id)
        .order_by(RemediationCase.created_at.desc())
    ).all()
    return [_case_payload(db, c) for c in cases]


@router.get("/organizations/{org_id}/remediation-cases/{case_id}")
def get_case(org_id: str, case_id: str, db: Session = Depends(get_db)):
    _get_org(db, org_id)
    case = _run(service.get_case, db, org_id, case_id)
    return _case_payload(db, case, detail=True)


@router.get(
    "/organizations/{org_id}/remediation-cases/{case_id}/link-suggestions",
    response_model=list[RemediationLinkSuggestionOut],
)
def link_suggestions(org_id: str, case_id: str, db: Session = Depends(get_db)):
    _get_org(db, org_id)
    return _run(service.link_suggestions, db, org_id, case_id)


@router.post("/organizations/{org_id}/remediation-cases/{case_id}/findings")
def link_finding(
    org_id: str, case_id: str, body: RemediationLinkDecision, db: Session = Depends(get_db)
):
    _get_org(db, org_id)
    case = _run(
        service.link_finding,
        db,
        org_id,
        case_id,
        body.finding_id,
        decision=body.decision,
        link_source=body.link_source,
        link_note=body.link_note,
        actor_label=body.actor_label,
    )
    return _case_payload(db, case, detail=True)


@router.delete("/organizations/{org_id}/remediation-cases/{case_id}/findings/{finding_id}")
def unlink_finding(
    org_id: str, case_id: str, finding_id: str, db: Session = Depends(get_db)
):
    _get_org(db, org_id)
    case = _run(service.unlink_finding, db, org_id, case_id, finding_id)
    return _case_payload(db, case, detail=True)


@router.post(
    "/organizations/{org_id}/remediation-cases/{case_id}/triage/redraft",
    response_model=RemediationTriageDraftOut,
)
def redraft_triage(
    org_id: str, case_id: str, body: RemediationActorBody, db: Session = Depends(get_db)
):
    _get_org(db, org_id)
    return _run(triage.draft_triage, db, org_id, case_id, actor_label=body.actor_label)


@router.post("/organizations/{org_id}/remediation-cases/{case_id}/triage/approve")
def approve_triage(
    org_id: str, case_id: str, body: RemediationTriageApprove, db: Session = Depends(get_db)
):
    _get_org(db, org_id)
    case = _run(
        service.approve_triage,
        db,
        org_id,
        case_id,
        body.triage_draft_id,
        classification=body.classification,
        correction_note=body.correction_note,
        scope=body.scope,
        scope_rationale=body.scope_rationale,
        reviewer_label=body.reviewer_label,
    )
    return _case_payload(db, case, detail=True)


@router.post("/organizations/{org_id}/remediation-cases/{case_id}/triage/reopen")
def reopen_triage(
    org_id: str, case_id: str, body: RemediationActorBody, db: Session = Depends(get_db)
):
    _get_org(db, org_id)
    case = _run(service.reopen_triage, db, org_id, case_id, actor_label=body.actor_label)
    return _case_payload(db, case, detail=True)


@router.post("/organizations/{org_id}/remediation-cases/{case_id}/plans")
def draft_plan(
    org_id: str,
    case_id: str,
    body: RemediationActorBody,
    db: Session = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    """Synchronous plan draft. Always returns the persisted plan row —
    including operational aborts (an ABSTAINED retrieval_error row rather
    than an ambiguous 5xx that would invite blind retries). Performs
    stale-PLANNING recovery when the previous lease expired."""
    _get_org(db, org_id)
    plan = _run(
        planner.draft_plan,
        db,
        session_factory,
        org_id,
        case_id,
        actor_label=body.actor_label,
    )
    return _plan_payload(plan)


@router.post("/organizations/{org_id}/remediation-cases/{case_id}/close")
def close_case(
    org_id: str, case_id: str, body: RemediationCloseBody, db: Session = Depends(get_db)
):
    _get_org(db, org_id)
    case = _run(
        service.close_case,
        db,
        org_id,
        case_id,
        close_note=body.close_note,
        actor_label=body.actor_label,
    )
    return _case_payload(db, case, detail=True)


@router.post("/organizations/{org_id}/remediation-cases/{case_id}/reopen")
def reopen_case(
    org_id: str, case_id: str, body: RemediationActorBody, db: Session = Depends(get_db)
):
    _get_org(db, org_id)
    case = _run(service.reopen_case, db, org_id, case_id, actor_label=body.actor_label)
    return _case_payload(db, case, detail=True)

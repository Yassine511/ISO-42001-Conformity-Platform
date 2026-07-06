"""M5 assessment run API: create/list/detail/resume/abandon + KB requirements.

Org scoping is structural: every route is nested under
/organizations/{org_id}/... and re-checks that the resource chain belongs to
the URL organization (404 otherwise) — point payloads and ids are never
trusted for isolation.

Execution: create/resume spawn a daemon runner thread (the pipeline is
synchronous). The in-process thread registry is local execution state; the DB
partial unique index (one RUNNING per org) and the org row lock are the
correctness mechanisms.
"""

from fastapi import APIRouter, Depends, HTTPException
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import Assessment, Finding, Organization
from app.pipeline import runner
from app.pipeline.dev_split import DEV_REQUIREMENT_IDS
from app.pipeline.graph import (
    AssessmentAlreadyRunningError,
    create_assessment,
    finalize_assessment,
)
from app.pipeline.state import AssessmentStatus
from app.schemas import (
    AssessmentCreate,
    AssessmentDetailOut,
    AssessmentListItemOut,
    AssessmentOut,
    AssessmentProgressOut,
    KbRequirementOut,
)
from app.services.retrieval import load_kb

router = APIRouter(prefix="/api", tags=["assessments"])

QDRANT_ERRORS = (ResponseHandlingException, UnexpectedResponse, ConnectionError)

ALREADY_RUNNING_FR = "Une évaluation est déjà en cours pour cette organisation."


def get_session_factory():
    """Session factory for the runner thread (overridden in tests: the thread
    must write to the same database as the request handlers)."""
    return SessionLocal


def _get_org(db: Session, org_id: str) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "Organisation introuvable.")
    return org


def _get_assessment(db: Session, org_id: str, assessment_id: str) -> Assessment:
    assessment = db.get(Assessment, assessment_id)
    if assessment is None or assessment.organization_id != org_id:
        raise HTTPException(404, "Évaluation introuvable pour cette organisation.")
    return assessment


def _manifest_complete(assessment: Assessment) -> bool:
    return bool(assessment.requirement_ids) and assessment.document_manifest is not None


def _list_item(assessment: Assessment, counts: dict) -> dict:
    c = counts.get(assessment.id, {})
    findings_done = c.get("VERIFIED", 0) + c.get("ABSTAINED", 0)
    progress = runner.PROGRESS.get(assessment.id)
    return {
        **AssessmentOut.model_validate(assessment).model_dump(),
        "total": len(assessment.requirement_ids or []),
        "findings_done": findings_done,
        "verified_count": c.get("VERIFIED", 0),
        "abstained_count": c.get("ABSTAINED", 0),
        "reviewed_count": c.get("reviewed", 0),
        "manifest_complete": _manifest_complete(assessment),
        "progress": AssessmentProgressOut(**progress) if progress else None,
    }


def _status_counts(db: Session, assessment_ids: list[str]) -> dict:
    """{assessment_id: {"VERIFIED": n, "ABSTAINED": n, "reviewed": n}} in one
    grouped query (no per-assessment N+1)."""
    counts: dict[str, dict] = {}
    if not assessment_ids:
        return counts
    rows = db.execute(
        select(Finding.assessment_id, Finding.status, func.count())
        .where(Finding.assessment_id.in_(assessment_ids))
        .group_by(Finding.assessment_id, Finding.status)
    ).all()
    for assessment_id, status, n in rows:
        counts.setdefault(assessment_id, {})[status] = n
    return counts


@router.post(
    "/organizations/{org_id}/assessments",
    response_model=AssessmentListItemOut,
    status_code=202,
)
def launch_assessment(
    org_id: str,
    body: AssessmentCreate,
    db: Session = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    _get_org(db, org_id)
    requirement_ids = body.requirement_ids if body.requirement_ids is not None else list(
        DEV_REQUIREMENT_IDS
    )
    try:
        assessment_id = create_assessment(
            session_factory, org_id, requirement_ids, k=body.k
        )
    except AssessmentAlreadyRunningError:
        raise HTTPException(409, ALREADY_RUNNING_FR)
    except IntegrityError:
        # concurrent creation slipped past the pre-check; the partial unique
        # index (one RUNNING per org) is the atomic gate
        raise HTTPException(409, ALREADY_RUNNING_FR)
    except QDRANT_ERRORS as exc:
        raise HTTPException(
            503, f"Index vectoriel indisponible — évaluation non créée : {exc}"
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    runner.launch(session_factory, assessment_id)
    assessment = db.get(Assessment, assessment_id)
    return _list_item(assessment, _status_counts(db, [assessment_id]))


@router.get(
    "/organizations/{org_id}/assessments", response_model=list[AssessmentListItemOut]
)
def list_assessments(org_id: str, db: Session = Depends(get_db)):
    _get_org(db, org_id)
    assessments = db.scalars(
        select(Assessment)
        .where(Assessment.organization_id == org_id)
        .order_by(Assessment.started_at.desc())
    ).all()
    counts = _status_counts(db, [a.id for a in assessments])
    return [_list_item(a, counts) for a in assessments]


@router.get(
    "/organizations/{org_id}/assessments/{assessment_id}",
    response_model=AssessmentDetailOut,
)
def get_assessment(org_id: str, assessment_id: str, db: Session = Depends(get_db)):
    _get_org(db, org_id)
    assessment = _get_assessment(db, org_id, assessment_id)
    findings = db.scalars(
        select(Finding).where(Finding.assessment_id == assessment_id)
    ).all()
    # manifest order (the run plan), unplanned/legacy findings last by creation
    order = {rid: i for i, rid in enumerate(assessment.requirement_ids or [])}
    findings.sort(key=lambda f: (order.get(f.requirement_id, len(order)), f.created_at))
    item = _list_item(assessment, _status_counts(db, [assessment_id]))
    return {**item, "findings": findings}


@router.post(
    "/organizations/{org_id}/assessments/{assessment_id}/resume",
    response_model=AssessmentListItemOut,
    status_code=202,
)
def resume_assessment(
    org_id: str,
    assessment_id: str,
    db: Session = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    _get_org(db, org_id)
    assessment = _get_assessment(db, org_id, assessment_id)
    if assessment.status != AssessmentStatus.RUNNING.value:
        raise HTTPException(
            409, f"Reprise impossible : statut {assessment.status} (RUNNING requis)."
        )
    if not _manifest_complete(assessment):
        raise HTTPException(
            422,
            "Reprise impossible : manifeste incomplet (évaluation antérieure à M5) ; "
            "créez une nouvelle évaluation.",
        )
    if not runner.launch(session_factory, assessment_id):
        raise HTTPException(409, "Cette évaluation est déjà en cours d'exécution.")
    return _list_item(assessment, _status_counts(db, [assessment_id]))


@router.post(
    "/organizations/{org_id}/assessments/{assessment_id}/abandon",
    response_model=AssessmentListItemOut,
    status_code=202,
)
def abandon_assessment(
    org_id: str,
    assessment_id: str,
    db: Session = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    """Cooperative cancellation. With a live in-process runner thread the flag
    is honoured after the current requirement; an orphaned RUNNING row (crash,
    restart, --reload) is finalized immediately so it never blocks the
    organization forever."""
    _get_org(db, org_id)
    assessment = _get_assessment(db, org_id, assessment_id)
    if assessment.status != AssessmentStatus.RUNNING.value:
        raise HTTPException(
            409, f"Abandon impossible : statut {assessment.status} (RUNNING requis)."
        )
    assessment.cancel_requested = True
    db.commit()
    if not runner.is_running_locally(assessment_id):
        finalize_assessment(
            session_factory,
            assessment_id,
            AssessmentStatus.FAILED,
            error="Abandonnée par l'utilisateur.",
        )
    db.expire_all()
    assessment = db.get(Assessment, assessment_id)
    return _list_item(assessment, _status_counts(db, [assessment_id]))


@router.get("/kb/requirements", response_model=list[KbRequirementOut])
def list_kb_requirements():
    """The 51 dev-split requirements, in frozen manifest order. The 14 M6
    holdout requirements are deliberately not exposed (their membership is
    itself holdout information)."""
    kb = load_kb()
    out = []
    for rid in DEV_REQUIREMENT_IDS:
        entry = kb["by_id"].get(rid)
        if entry is None:  # corpus drift: validator + tests catch this
            continue
        out.append(
            KbRequirementOut(
                id=rid,
                domain=entry.get("domain"),
                requirement_fr=entry["requirement_fr"],
            )
        )
    return out

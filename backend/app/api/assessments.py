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

from datetime import datetime, timezone

from app.api.deps import get_current_user, require_org_member
from app.db import SessionLocal, get_db
from app.models import Assessment, AssessmentAttempt, Finding, FindingReview, Organization
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
    AttemptDetailOut,
    FindingDetailOut,
    KbRequirementOut,
    LlmCallSummaryOut,
    ReviewDecision,
)
from app.services.provenance import source_slice
from app.services.retrieval import load_kb

# Every route here is org-scoped: membership enforced once at router level
# (M10). /kb/requirements has no org in its path -> lives on kb_router below.
router = APIRouter(
    prefix="/api",
    tags=["assessments"],
    dependencies=[Depends(require_org_member)],
)
# KB content is app data, not org data: any authenticated user may read it.
kb_router = APIRouter(
    prefix="/api", tags=["assessments"], dependencies=[Depends(get_current_user)]
)

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
    reviewed = db.execute(
        select(Finding.assessment_id, func.count())
        .where(
            Finding.assessment_id.in_(assessment_ids),
            Finding.review_status == "CONFIRMED",
        )
        .group_by(Finding.assessment_id)
    ).all()
    for assessment_id, n in reviewed:
        counts.setdefault(assessment_id, {})["reviewed"] = n
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
    _get_assessment(db, org_id, assessment_id)
    # Check-and-set under the row lock (finalize_assessment takes the same
    # lock): the RUNNING check and the flag write are atomic, so the flag can
    # never land on a row a concurrent runner just finalized — terminal
    # metadata stays immutable.
    assessment = db.get(Assessment, assessment_id, with_for_update=True)
    if assessment.status != AssessmentStatus.RUNNING.value:
        db.rollback()
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


# ------------------------------------------------------------ HITL review


def _get_finding(db: Session, org_id: str, assessment_id: str, finding_id: str) -> Finding:
    """404 unless the finding -> assessment -> organization chain matches the
    URL exactly (org scoping is structural, never trusted from the id)."""
    finding = db.get(Finding, finding_id)
    if (
        finding is None
        or finding.assessment_id != assessment_id
        or finding.assessment.organization_id != org_id
    ):
        raise HTTPException(404, "Constat introuvable pour cette évaluation.")
    return finding


def _finding_detail(db: Session, finding: Finding) -> dict:
    # Requirement snapshot with documented legacy fallback: NULL snapshot rows
    # (pre-0012) may use the live KB only when the corpus_version still
    # matches — text from another corpus version must never be presented as
    # what was assessed.
    requirement_fr, domain = finding.requirement_fr, finding.domain
    corpus_mismatch = False
    if requirement_fr is None:
        kb = load_kb()
        entry = kb["by_id"].get(finding.requirement_id)
        if entry is not None and kb["corpus_version"] == finding.assessment.corpus_version:
            requirement_fr = entry["requirement_fr"]
            domain = domain or entry.get("domain")
        else:
            corpus_mismatch = True

    # Evidence text at the persisted offsets, fail-closed. Two kinds:
    # - "verified" (exact match): cross-checked against the verified model
    #   quote — this is the authoritative citation display text;
    # - "candidate" (fuzzy near-match kept for priority human review): a
    #   bounded source LOCATION, deliberately NOT cross-checked (a near-match
    #   never normalizes to the model quote, and the quote may be absent after
    #   a failed repair) and never presented as a verified citation.
    source_quote = source_quote_error = None
    source_quote_kind = None
    if finding.matched_chunk_id is not None:
        source = next(
            (
                item
                for item in (finding.retrieved or [])
                if item.get("result_id") == finding.matched_chunk_id
            ),
            {},
        )
        match = {"match_start": finding.match_start, "match_end": finding.match_end}
        exact = finding.match_method == "exact"
        source_quote, source_quote_error = source_slice(
            source, match, finding.policy_quote if exact else None
        )
        if source_quote is not None:
            source_quote_kind = "verified" if exact else "candidate"

    attempts = db.scalars(
        select(AssessmentAttempt)
        .where(
            AssessmentAttempt.assessment_id == finding.assessment_id,
            AssessmentAttempt.requirement_id == finding.requirement_id,
        )
        .order_by(AssessmentAttempt.attempt_number)
    ).all()
    attempt_history = [
        AttemptDetailOut(
            attempt_number=a.attempt_number,
            prompt_version=a.prompt_version,
            parsed_ok=a.parsed_ok,
            verifier_errors=a.verifier_errors,
            llm_calls=[LlmCallSummaryOut.model_validate(c) for c in a.llm_calls],
        )
        for a in attempts
    ]

    base = {
        attr: getattr(finding, attr)
        for attr in (
            "id",
            "assessment_id",
            "requirement_id",
            "status",
            "verdict",
            "abstain_reason",
            "confidence",
            "policy_quote",
            "clause_ref",
            "rationale",
            "matched_chunk_id",
            "match_start",
            "match_end",
            "match_method",
            "match_score",
            "attempts",
            "final_model",
            "final_provider",
            "retrieved",
            "audit_log",
            "review_status",
            "review_action",
            "human_verdict",
            "human_rationale",
            "review_note",
            "reviewed_at",
            "review_count",
            "created_at",
        )
    }
    return {
        **base,
        "requirement_fr": requirement_fr,
        "domain": domain,
        "corpus_mismatch": corpus_mismatch,
        "source_quote": source_quote,
        "source_quote_error": source_quote_error,
        "source_quote_kind": source_quote_kind,
        "attempt_history": attempt_history,
        "reviews": finding.reviews,
    }


@router.get(
    "/organizations/{org_id}/assessments/{assessment_id}/findings/{finding_id}",
    response_model=FindingDetailOut,
)
def get_finding(
    org_id: str, assessment_id: str, finding_id: str, db: Session = Depends(get_db)
):
    _get_org(db, org_id)
    finding = _get_finding(db, org_id, assessment_id, finding_id)
    return _finding_detail(db, finding)


@router.post(
    "/organizations/{org_id}/assessments/{assessment_id}/findings/{finding_id}/review",
    response_model=FindingDetailOut,
)
def review_finding(
    org_id: str,
    assessment_id: str,
    finding_id: str,
    body: ReviewDecision,
    db: Session = Depends(get_db),
):
    """Record the human decision. Writes ONLY review columns + an immutable
    FindingReview row — the AI draft is never modified. Re-review is allowed
    (single auditor correcting themself); the projection is fully rewritten
    (stale optional fields reset) and history keeps every decision."""
    _get_org(db, org_id)
    _get_finding(db, org_id, assessment_id, finding_id)
    # Row lock: concurrent re-reviews serialize so sequence numbers and the
    # projection cannot interleave (no-op on SQLite unit tests).
    finding = db.get(Finding, finding_id, with_for_update=True)

    if body.action in ("approve", "edit") and finding.status != "VERIFIED":
        raise HTTPException(
            422,
            "Un constat en abstention nécessite votre verdict : utilisez "
            "« remplacer » (override).",
        )
    if body.action == "approve":
        human_verdict = finding.verdict
        human_rationale = body.human_rationale  # optional commentary
    elif body.action == "edit":
        if not body.human_rationale:
            raise HTTPException(
                422, "L'action « modifier » exige votre justification (human_rationale)."
            )
        human_verdict = finding.verdict  # edit keeps the AI verdict
        human_rationale = body.human_rationale
    else:  # override
        if not body.human_verdict or not body.human_rationale:
            raise HTTPException(
                422,
                "L'action « remplacer » exige un verdict (human_verdict) et une "
                "justification (human_rationale).",
            )
        human_verdict = body.human_verdict
        human_rationale = body.human_rationale
    if human_verdict is None:  # approve on a (VERIFIED) finding without verdict
        raise HTTPException(
            422, "Ce constat n'a pas de verdict IA : utilisez « remplacer » (override)."
        )

    sequence = finding.review_count + 1
    db.add(
        FindingReview(
            finding_id=finding.id,
            sequence=sequence,
            action=body.action,
            human_verdict=human_verdict,
            human_rationale=human_rationale,
            review_note=body.review_note,
            reviewer_label=body.reviewer_label,
        )
    )
    # Full projection rewrite: stale optional fields from a previous decision
    # never leak into the new one.
    finding.review_status = "CONFIRMED"
    finding.review_action = body.action
    finding.human_verdict = human_verdict
    finding.human_rationale = human_rationale
    finding.review_note = body.review_note
    finding.reviewed_at = datetime.now(timezone.utc)
    finding.review_count = sequence
    db.commit()
    db.refresh(finding)
    return _finding_detail(db, finding)


@kb_router.get("/kb/requirements", response_model=list[KbRequirementOut])
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

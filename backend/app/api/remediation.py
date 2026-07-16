"""M7a remediation case API: creation from a confirmed gap finding, linking,
triage draft/approve/reopen, close/reopen.

Org scoping is structural (assessments.py pattern): every route nests under
/organizations/{org_id}/... and the service re-checks the resource chain.
Service exceptions map: NotFound -> 404, Conflict -> 409, Invalid -> 422.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import (
    Organization,
    PatchProposal,
    RemediationArtifact,
    RemediationCase,
)
from app.remediation import actions, patcher, planner, reassessment, service, triage
from app.services.run_guard import RUNNING_CONFLICT_FR
from app.remediation.service import (
    RemediationConflictError,
    RemediationInvalidError,
    RemediationNotFoundError,
)
from app.services.provenance import source_slice
from app.services import scoring
from app.schemas import (
    PatchDecisionBody,
    PatchProposalCreate,
    RemediationActorBody,
    RemediationCaseCreate,
    RemediationCaseFindingOut,
    RemediationCaseOut,
    RemediationCasePlanningBody,
    RemediationCloseBody,
    RemediationEventOut,
    RemediationLinkDecision,
    RemediationActionOut,
    RemediationActionReview,
    RemediationEffectivenessBody,
    RemediationLifecycleBody,
    RemediationLinkSuggestionOut,
    RemediationPlanOut,
    RemediationReassessmentCreate,
    RemediationReassessmentOut,
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


def _get_case(db: Session, org_id: str, case_id: str) -> RemediationCase:
    """Tenant guard: the case must exist AND belong to the org in the URL.
    Direct-read routes (artifact list/download) must not trust case_id alone —
    a case id from another org would otherwise leak its rows."""
    case = db.get(RemediationCase, case_id)
    if case is None or case.organization_id != org_id:
        raise HTTPException(404, "Cas de remédiation introuvable.")
    return case


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
    # compact workflow summary (0018): plan status / blocker / action counts /
    # next-action key / closure recommendation — the frontend translates the
    # keys through its central display module, raw keys never render.
    base["workflow"] = service.workflow_summary(case)
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
    body["actions"] = [_action_payload(a, plan) for a in plan.actions]
    return body


def _action_payload(action, plan=None) -> dict:
    """Action + the human-approved effective scope + the AUTHORITATIVE
    citation display text: a raw source slice at the persisted offsets via
    source_slice() (fail-closed — never the model's policy_quote)."""
    body = RemediationActionOut.model_validate(action).model_dump()
    body["effective_requirement_ids"] = [
        r.requirement_id for r in action.requirements
    ]
    plan = plan if plan is not None else action.plan
    # M8 read-only severity-derived priority suggestion: the action's own
    # scope (effective ids once reviewed, else the AI proposal) matched
    # against the IMMUTABLE case-link snapshots; carries its policy version
    # so a future policy bump cannot silently change the human prefill.
    # Never persisted — the human priority decision stays mandatory.
    body.update(
        scoring.suggested_priority_for_action(
            body["effective_requirement_ids"]
            or list(action.ai_impacted_requirement_ids or []),
            [
                (link.finding_requirement_id, link.finding_human_verdict)
                for link in plan.case.finding_links
            ],
        )
    )
    source_quote = source_quote_error = None
    if action.matched_chunk_id is not None:
        source = next(
            (
                item
                for item in (plan.retrieved or [])
                if item.get("result_id") == action.matched_chunk_id
            ),
            {},
        )
        match = {"match_start": action.match_start, "match_end": action.match_end}
        source_quote, source_quote_error = source_slice(
            source, match, action.policy_quote
        )
    body["source_quote"] = source_quote
    body["source_quote_error"] = source_quote_error
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


@router.put("/organizations/{org_id}/remediation-cases/{case_id}/planning")
def update_case_planning(
    org_id: str,
    case_id: str,
    body: RemediationCasePlanningBody,
    db: Session = Depends(get_db),
):
    """Human case-planning update (owner role / deadline / closure criterion)
    under an optimistic revision check; every edit is an append-only
    case_planning_updated event. 409 on a stale expected_revision."""
    _get_org(db, org_id)
    case = _run(
        service.update_case_planning,
        db,
        org_id,
        case_id,
        expected_revision=body.expected_revision,
        owner_role=body.owner_role,
        due_date=body.due_date,
        closure_criterion=body.closure_criterion,
        editor_label=body.editor_label,
    )
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


# ------------------------------------------------------------- M7b patches


def _activation_response(result: dict):
    """Deterministic outcome -> HTTP mapping. Duplicate/racing requests get
    the candidate's REAL state (200 done / 202 in flight / 409 typed), never
    an opaque conflict."""
    outcome = result["outcome"]
    if outcome in ("activated", "already_active", "rejected"):
        return result
    if outcome == "pending":
        return JSONResponse(status_code=202, content=result)
    if outcome == "assessment_conflict":
        return JSONResponse(
            status_code=409,
            content={**result, "detail": RUNNING_CONFLICT_FR + " La version en attente pourra être reprise ensuite."},
        )
    if outcome == "index_failed":
        return JSONResponse(
            status_code=503,
            content={
                **result,
                "detail": "Indexation vectorielle échouée ; la version est "
                "conservée en INDEX_FAILED et peut être reprise.",
            },
        )
    if outcome.startswith("abandoned:"):
        return JSONResponse(
            status_code=409,
            content={
                **result,
                "detail": "Activation abandonnée : " + outcome.split(":", 1)[1]
                + ". Redemandez un correctif sur l'état actuel.",
            },
        )
    return result


@router.post(
    "/organizations/{org_id}/remediation-cases/{case_id}/actions/{action_id}/patch-proposals",
    status_code=201,
)
def create_patch_proposal(
    org_id: str,
    case_id: str,
    action_id: str,
    body: PatchProposalCreate,
    db: Session = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    """Synchronous anchored-patch draft against the human-confirmed TXT/MD
    target. Always returns the persisted proposal (VERIFIED or ABSTAINED)."""
    _get_org(db, org_id)
    proposal = _run(
        patcher.draft_patch_proposal,
        db,
        session_factory,
        org_id,
        case_id,
        action_id,
        body.document_id,
        actor_label=body.actor_label,
    )
    return _run(patcher.proposal_view, db, org_id, case_id, proposal.id)


@router.get(
    "/organizations/{org_id}/remediation-cases/{case_id}/actions/{action_id}/patch-proposals",
)
def list_patch_proposals(
    org_id: str, case_id: str, action_id: str, db: Session = Depends(get_db)
):
    _get_org(db, org_id)
    ids = db.scalars(
        select(PatchProposal.id)
        .where(
            PatchProposal.case_id == case_id,
            PatchProposal.action_id == action_id,
        )
        .order_by(PatchProposal.created_at)
    ).all()
    return [_run(patcher.proposal_view, db, org_id, case_id, pid) for pid in ids]


@router.get(
    "/organizations/{org_id}/remediation-cases/{case_id}/patch-proposals/{proposal_id}",
)
def get_patch_proposal(
    org_id: str, case_id: str, proposal_id: str, db: Session = Depends(get_db)
):
    """Diff review data: server-derived source slice at the RESOLVED anchor
    span + context — never the model quote as evidence."""
    _get_org(db, org_id)
    return _run(patcher.proposal_view, db, org_id, case_id, proposal_id)


@router.post(
    "/organizations/{org_id}/remediation-cases/{case_id}/patch-proposals/{proposal_id}/decision",
)
def decide_patch_proposal(
    org_id: str,
    case_id: str,
    proposal_id: str,
    body: PatchDecisionBody,
    db: Session = Depends(get_db),
):
    """approve/edit apply the FINAL HUMAN text through the token-fenced
    two-phase activation; reject records the decision only."""
    _get_org(db, org_id)
    result = _run(
        patcher.decide_patch,
        db,
        org_id,
        case_id,
        proposal_id,
        decision=body.decision,
        final_text_fr=body.final_text_fr,
        actor_label=body.actor_label,
    )
    return _activation_response(result)


@router.post(
    "/organizations/{org_id}/remediation-cases/{case_id}/patch-proposals/{proposal_id}/recover",
)
def recover_patch_proposal(
    org_id: str,
    case_id: str,
    proposal_id: str,
    body: RemediationActorBody,
    db: Session = Depends(get_db),
):
    """Re-drive a stranded activation (crash / timeout / assessment
    conflict). Idempotent: an already-ACTIVE result returns 200."""
    _get_org(db, org_id)
    result = _run(
        patcher.recover_patch_activation,
        db,
        org_id,
        case_id,
        proposal_id,
        actor_label=body.actor_label,
    )
    return _activation_response(result)


def _artifact_payload(artifact) -> dict:
    return {
        "id": artifact.id,
        "case_id": artifact.case_id,
        "action_id": artifact.action_id,
        "document_id": artifact.document_id,
        "document_version_id": artifact.document_version_id,
        "canonical_format": artifact.canonical_format,
        "status": artifact.status,
        "abstain_reason": artifact.abstain_reason,
        "verifier_errors": artifact.verifier_errors,
        "filename": artifact.filename,
        "content_md": artifact.content_md,
        "rationale": artifact.rationale,
        "attempts": artifact.attempts,
        "requirement_ids": artifact.requirement_ids,
        "created_at": artifact.created_at.isoformat(),
    }


@router.post(
    "/organizations/{org_id}/remediation-cases/{case_id}/actions/{action_id}/artifacts",
    status_code=201,
)
def create_artifact(
    org_id: str,
    case_id: str,
    action_id: str,
    body: PatchProposalCreate,
    db: Session = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    """Markdown revision proposal for a PDF/DOCX target — never a document
    version; the human uploads the real revised file themselves (superseding
    upload, which may cite this artifact as lineage)."""
    _get_org(db, org_id)
    artifact = _run(
        patcher.draft_artifact,
        db,
        session_factory,
        org_id,
        case_id,
        action_id,
        body.document_id,
        actor_label=body.actor_label,
    )
    return _artifact_payload(artifact)


@router.get(
    "/organizations/{org_id}/remediation-cases/{case_id}/actions/{action_id}/artifacts",
)
def list_artifacts(
    org_id: str, case_id: str, action_id: str, db: Session = Depends(get_db)
):
    _get_case(db, org_id, case_id)  # tenant guard: case must belong to org
    rows = db.scalars(
        select(RemediationArtifact)
        .where(
            RemediationArtifact.case_id == case_id,
            RemediationArtifact.action_id == action_id,
        )
        .order_by(RemediationArtifact.created_at)
    ).all()
    return [_artifact_payload(a) for a in rows]


ARTIFACT_HEADER_FR = (
    "> **Proposition de rédaction — brouillon IA, document original inchangé.**\n"
    "> Ce fichier n'est PAS une version du document : seule une personne peut\n"
    "> téléverser la révision réelle (PDF/DOCX), qui créera la nouvelle version.\n\n"
)


@router.get(
    "/organizations/{org_id}/remediation-cases/{case_id}/artifacts/{artifact_id}/download",
)
def download_artifact(
    org_id: str, case_id: str, artifact_id: str, db: Session = Depends(get_db)
):
    _get_case(db, org_id, case_id)  # tenant guard: case must belong to org
    artifact = db.get(RemediationArtifact, artifact_id)
    if artifact is None or artifact.case_id != case_id:
        raise HTTPException(404, "Artefact introuvable.")
    if artifact.status != "VERIFIED":
        raise HTTPException(409, "Seul un artefact VÉRIFIÉ peut être téléchargé.")
    content = ARTIFACT_HEADER_FR + artifact.content_md
    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )


@router.post(
    "/organizations/{org_id}/remediation-cases/{case_id}/actions/{action_id}/review",
)
def review_action(
    org_id: str,
    case_id: str,
    action_id: str,
    body: RemediationActionReview,
    db: Session = Depends(get_db),
):
    _get_org(db, org_id)
    row = _run(
        actions.review_action,
        db,
        org_id,
        case_id,
        action_id,
        action=body.action,
        description=body.description,
        rationale=body.rationale,
        owner_role=body.owner_role,
        success_criterion=body.success_criterion,
        priority=body.priority,
        due_date=body.due_date,
        impacted_requirement_ids=body.impacted_requirement_ids,
        review_note=body.review_note,
        reviewer_label=body.reviewer_label,
    )
    return _action_payload(row)


@router.post(
    "/organizations/{org_id}/remediation-cases/{case_id}/actions/{action_id}/lifecycle",
)
def change_lifecycle(
    org_id: str,
    case_id: str,
    action_id: str,
    body: RemediationLifecycleBody,
    db: Session = Depends(get_db),
):
    _get_org(db, org_id)
    row = _run(
        actions.change_lifecycle,
        db,
        org_id,
        case_id,
        action_id,
        lifecycle=body.lifecycle,
        actor_label=body.actor_label,
    )
    return _action_payload(row)


@router.post(
    "/organizations/{org_id}/remediation-cases/{case_id}/actions/{action_id}/effectiveness",
)
def record_effectiveness(
    org_id: str,
    case_id: str,
    action_id: str,
    body: RemediationEffectivenessBody,
    db: Session = Depends(get_db),
):
    _get_org(db, org_id)
    row = _run(
        actions.record_effectiveness,
        db,
        org_id,
        case_id,
        action_id,
        effectiveness=body.effectiveness,
        note=body.note,
        reassessment_id=body.reassessment_id,
        actor_label=body.actor_label,
    )
    return _action_payload(row)


@router.post(
    "/organizations/{org_id}/remediation-cases/{case_id}/reassessments",
    response_model=RemediationReassessmentOut,
    status_code=202,
)
def launch_reassessment(
    org_id: str,
    case_id: str,
    body: RemediationReassessmentCreate,
    db: Session = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    _get_org(db, org_id)
    return _run(
        reassessment.launch_reassessment,
        db,
        session_factory,
        org_id,
        case_id,
        selected_action_ids=body.selected_action_ids,
        actor_label=body.actor_label,
    )


@router.get(
    "/organizations/{org_id}/remediation-cases/{case_id}/reassessments",
    response_model=list[RemediationReassessmentOut],
)
def list_reassessments(
    org_id: str,
    case_id: str,
    db: Session = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    _get_org(db, org_id)
    case = _run(service.get_case, db, org_id, case_id)
    _run(reassessment.reconcile_pending, db, session_factory, org_id, case.id)
    db.expire_all()
    from app.models import RemediationReassessment

    return db.scalars(
        select(RemediationReassessment)
        .where(RemediationReassessment.case_id == case_id)
        .order_by(RemediationReassessment.created_at)
    ).all()


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

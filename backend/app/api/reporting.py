"""M8 Node ⑤ reporting API: conformity, trust panel, risk register.

Read-only, deterministic, no AI. Consistency by construction: on PostgreSQL
every request runs inside ONE REPEATABLE READ / READ ONLY transaction opened
BEFORE any query (including the org lookup — a plain get_db session would
already have opened a default READ COMMITTED transaction), and every number in
a response comes from the single materialized ReportingScope built inside it.
On SQLite (unit tests) the eager materialization alone provides the same
calculator interface.

Callers may pin ?scoring_policy_version= (422 on unknown, listing the known
versions); the chosen version is echoed in every response so a future policy
bump can never silently rescore an old report.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import Organization
from app.schemas import SoaDecisionBody
from app.services import report_pdf as report_pdf_service
from app.services import scoring
from app.services import soa as soa_service
from app.services.scoring_policy import SCORING_POLICIES

router = APIRouter(prefix="/api", tags=["reporting"])


def get_reporting_db():
    """Isolated read-only session — REPEATABLE READ established before the
    first statement so the whole report reads one database snapshot."""
    db = SessionLocal()
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.connection(
                execution_options={
                    "isolation_level": "REPEATABLE READ",
                    "postgresql_readonly": True,
                }
            )
        yield db
    finally:
        db.close()


def _get_org(db: Session, org_id: str) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "Organisation introuvable.")
    return org


def _build_scope(
    db: Session,
    org_id: str,
    assessment_id: str | None,
    scoring_policy_version: str | None,
    include_preliminary: bool,
) -> scoring.ReportingScope:
    _get_org(db, org_id)
    try:
        return scoring.build_reporting_scope(
            db,
            org_id,
            assessment_id,
            include_preliminary=include_preliminary,
            scoring_policy_version=scoring_policy_version,
        )
    except KeyError:
        raise HTTPException(
            422,
            "Version de politique de notation inconnue. Versions disponibles : "
            + ", ".join(sorted(SCORING_POLICIES)),
        )
    except LookupError:
        raise HTTPException(404, "Évaluation introuvable pour cette organisation.")


@router.get("/organizations/{org_id}/reporting/conformity")
def conformity(
    org_id: str,
    assessment_id: str | None = None,
    scoring_policy_version: str | None = None,
    include_preliminary: bool = False,
    db: Session = Depends(get_reporting_db),
):
    scope = _build_scope(db, org_id, assessment_id, scoring_policy_version, include_preliminary)
    return scoring.conformity_summary(scope)


@router.get("/organizations/{org_id}/reporting/risk-register")
def risk_register(
    org_id: str,
    assessment_id: str | None = None,
    scoring_policy_version: str | None = None,
    include_preliminary: bool = False,
    db: Session = Depends(get_reporting_db),
):
    scope = _build_scope(db, org_id, assessment_id, scoring_policy_version, include_preliminary)
    return scoring.risk_register(scope)


@router.get("/organizations/{org_id}/reporting/soa")
def soa(
    org_id: str,
    assessment_id: str | None = None,
    scoring_policy_version: str | None = None,
    include_preliminary: bool = False,
    db: Session = Depends(get_reporting_db),
):
    scope = _build_scope(db, org_id, assessment_id, scoring_policy_version, include_preliminary)
    return soa_service.soa_table(db, scope)


@router.put("/organizations/{org_id}/reporting/soa/{control_id}")
def put_soa_control(
    org_id: str,
    control_id: str,
    body: SoaDecisionBody,
    db: Session = Depends(get_db),
):
    """Record one immutable applicability decision (org row lock inside)."""
    try:
        projection = soa_service.record_decision(
            db,
            org_id,
            control_id,
            applicable=body.applicable,
            justification_fr=body.justification_fr,
            editor_label=body.editor_label,
        )
    except soa_service.SoaOrganizationNotFoundError:
        raise HTTPException(404, "Organisation introuvable.")
    except soa_service.SoaUnknownControlError:
        raise HTTPException(404, "Contrôle Annexe A inconnu.")
    return {
        "control_id": projection.control_id,
        "applicable": projection.applicable,
        "justification_fr": projection.justification_fr,
        "editor_label": projection.editor_label,
        "decision_count": projection.decision_count,
        "updated_at": projection.updated_at.isoformat(),
    }


@router.get("/organizations/{org_id}/reporting/soa/{control_id}/history")
def soa_history(org_id: str, control_id: str, db: Session = Depends(get_db)):
    _get_org(db, org_id)
    try:
        decisions = soa_service.decision_history(db, org_id, control_id)
    except soa_service.SoaUnknownControlError:
        raise HTTPException(404, "Contrôle Annexe A inconnu.")
    return [
        {
            "sequence": d.sequence,
            "applicable": d.applicable,
            "justification_fr": d.justification_fr,
            "editor_label": d.editor_label,
            "created_at": d.created_at.isoformat(),
        }
        for d in decisions
    ]


@router.get("/organizations/{org_id}/reporting/report.pdf")
def report_pdf(
    org_id: str,
    assessment_id: str | None = None,
    scoring_policy_version: str | None = None,
    include_preliminary: bool = False,
    db: Session = Depends(get_reporting_db),
):
    """Deterministic PDF report over ONE ReportingScope snapshot.

    Official assessment reports require COMPLETED (typed 409 otherwise);
    include_preliminary=true explicitly allows a preview PDF carrying the
    «préliminaire» banner. Only a recognized WeasyPrint import/native-load
    failure maps to 503 — template/render defects stay 500."""
    scope = _build_scope(
        db, org_id, assessment_id, scoring_policy_version, include_preliminary
    )
    if (
        scope.mode == "assessment"
        and scope.assessment_status != "COMPLETED"
        and not include_preliminary
    ):
        raise HTTPException(
            409,
            "Évaluation non terminée : un rapport officiel exige le statut COMPLETED. "
            "Utilisez include_preliminary=true pour un aperçu explicitement préliminaire.",
        )
    context = report_pdf_service.build_report_context(db, scope)
    try:
        pdf_bytes = report_pdf_service.render_report_pdf(context)
    except report_pdf_service.PdfUnavailableError:
        raise HTTPException(
            503,
            "Export PDF indisponible sur cet environnement (bibliothèques natives "
            "WeasyPrint manquantes — utilisez le déploiement Docker).",
        )
    filename = f"rapport_iso42001_{assessment_id or org_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/organizations/{org_id}/reporting/trust")
def trust(
    org_id: str,
    assessment_id: str | None = None,
    scoring_policy_version: str | None = None,
    include_preliminary: bool = False,
    db: Session = Depends(get_reporting_db),
):
    scope = _build_scope(db, org_id, assessment_id, scoring_policy_version, include_preliminary)
    return scoring.trust_panel(db, scope)

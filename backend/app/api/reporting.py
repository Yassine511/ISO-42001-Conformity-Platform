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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Organization
from app.services import scoring
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

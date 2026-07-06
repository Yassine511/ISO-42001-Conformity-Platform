"""Org-level mutual exclusion between assessment runs and corpus mutations.

Uploading, deleting or re-indexing documents while an assessment is RUNNING
would change what later requirements retrieve — the frozen document_manifest
would silently stop describing the run. Handlers that mutate an organization's
corpus (and assessment creation itself) serialize on the organization row via
SELECT ... FOR UPDATE, then check for a RUNNING assessment under that lock.

SQLite (unit tests) ignores FOR UPDATE — the PG-backed integration test
validates the real serialization; the partial unique index
uq_assessments_one_running remains the DB-level backstop for creation.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assessment, Organization

RUNNING_CONFLICT_FR = (
    "Impossible pendant qu'une évaluation est en cours pour cette organisation — "
    "attendez sa fin ou abandonnez-la."
)


def lock_organization(db: Session, org_id: str) -> Organization | None:
    """Lock the organization row for the caller's transaction (None = 404)."""
    return db.get(Organization, org_id, with_for_update=True)


def running_assessment_id(db: Session, org_id: str) -> str | None:
    return db.scalar(
        select(Assessment.id).where(
            Assessment.organization_id == org_id,
            Assessment.status == "RUNNING",
        )
    )

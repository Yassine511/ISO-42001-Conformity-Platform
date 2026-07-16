"""M10 shared auth dependencies.

Enforcement model: every business router is guarded at the APIRouter level
with `dependencies=[Depends(require_org_member)]` (FastAPI resolves the
`org_id` path param inside the dependency, so individual routes stay
untouched). Routes that identify a resource WITHOUT an org in the path
(DELETE /api/documents/{id}, the /versions/... family) resolve the document
to its organization first via `require_document_access`.

Membership failures return 404 («Organisation introuvable.»), never 403 —
a non-member must not learn that someone else's org id exists. This mirrors
the pre-auth guard convention (wrong org in the path always read as 404).
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Document, User
from app.services import auth as auth_service

SESSION_COOKIE = "int102_session"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        user = auth_service.resolve_session(db, raw_token)
        if user is not None:
            return user
    raise HTTPException(401, "Authentification requise.")


def require_org_member(
    org_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if not auth_service.is_member(db, user.id, org_id):
        raise HTTPException(404, "Organisation introuvable.")
    return user


def require_document_access(
    document_id: str,  # name must match the routes' path param
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Guard for org-unscoped document routes: document -> owning org ->
    membership. Unknown doc and non-member doc collapse into the same 404."""
    doc = db.get(Document, document_id)
    if doc is None or not auth_service.is_member(db, user.id, doc.organization_id):
        raise HTTPException(404, "Document introuvable.")
    return user

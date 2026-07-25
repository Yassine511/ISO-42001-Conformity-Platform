import threading

from fastapi import APIRouter, Depends, HTTPException
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_org_member
from app.db import get_db
from app.models import Organization
from app.schemas import IndexReport, KbIndexReport, SearchRequest, SearchResult
from app.services import retrieval
from app.services.run_guard import RUNNING_CONFLICT_FR, lock_organization, running_assessment_id

router = APIRouter(prefix="/api", tags=["retrieval"])

# Everything qdrant-client raises when the vector store is down or misbehaving.
QDRANT_ERRORS = (ResponseHandlingException, UnexpectedResponse, ConnectionError)


@router.post(
    "/organizations/{org_id}/index",
    response_model=IndexReport,
    dependencies=[Depends(require_org_member)],
)
def index_organization(org_id: str, db: Session = Depends(get_db)):
    # Org row lock + RUNNING check: re-indexing mid-run would change the chunk
    # set later requirements retrieve from (frozen-manifest invariant).
    if not lock_organization(db, org_id):
        raise HTTPException(404, "Organisation introuvable.")
    if running_assessment_id(db, org_id):
        raise HTTPException(409, RUNNING_CONFLICT_FR)
    try:
        return retrieval.index_organization(db, org_id)
    except QDRANT_ERRORS as exc:
        db.rollback()
        raise HTTPException(503, f"Index vectoriel indisponible : {exc}")


# Single-flight gate for the KB reindex. index_kb() is a full reconciliation
# (upsert every requirement, then delete every point that is not canonical):
# two of them interleaving means one can delete points the other just wrote,
# and it is an embedding-heavy, unbounded-cost operation that ANY authenticated
# user can trigger. Non-blocking — a concurrent caller gets 409, never a queue.
#
# This is process-local, which matches the deployment (single worker, see
# README «Déploiement»); the real authorization fix (operator-only) needs the
# role column M10 deliberately left out and is deferred to M11.
_KB_INDEX_LOCK = threading.Lock()


# KB reindex touches shared app data only — authenticated, not org-scoped.
@router.post(
    "/kb/index", response_model=KbIndexReport, dependencies=[Depends(get_current_user)]
)
def index_kb():
    if not _KB_INDEX_LOCK.acquire(blocking=False):
        raise HTTPException(
            409,
            "Une réindexation de la base de connaissances est déjà en cours ; "
            "réessayez dans un instant.",
        )
    try:
        return retrieval.index_kb()
    except FileNotFoundError:
        raise HTTPException(500, "Base de connaissances introuvable (corpus_path mal configuré ?).")
    except QDRANT_ERRORS as exc:
        raise HTTPException(503, f"Index vectoriel indisponible : {exc}")
    finally:
        _KB_INDEX_LOCK.release()


@router.post(
    "/organizations/{org_id}/search",
    response_model=list[SearchResult],
    dependencies=[Depends(require_org_member)],
)
def search(org_id: str, body: SearchRequest, db: Session = Depends(get_db)):
    if not db.get(Organization, org_id):
        raise HTTPException(404, "Organisation introuvable.")
    try:
        items = retrieval.hybrid_search(db, org_id, body.query, body.k, body.scope)
    except retrieval.CorpusChangedError as exc:
        raise HTTPException(409, str(exc))  # retryable: a version activation raced us
    except QDRANT_ERRORS as exc:
        raise HTTPException(503, f"Index vectoriel indisponible : {exc}")
    return [SearchResult(**item.__dict__) for item in items]

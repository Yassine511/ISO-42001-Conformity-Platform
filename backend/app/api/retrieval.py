from fastapi import APIRouter, Depends, HTTPException
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization
from app.schemas import IndexReport, KbIndexReport, SearchRequest, SearchResult
from app.services import retrieval
from app.services.run_guard import RUNNING_CONFLICT_FR, lock_organization, running_assessment_id

router = APIRouter(prefix="/api", tags=["retrieval"])

# Everything qdrant-client raises when the vector store is down or misbehaving.
QDRANT_ERRORS = (ResponseHandlingException, UnexpectedResponse, ConnectionError)


@router.post("/organizations/{org_id}/index", response_model=IndexReport)
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


@router.post("/kb/index", response_model=KbIndexReport)
def index_kb():
    try:
        return retrieval.index_kb()
    except FileNotFoundError:
        raise HTTPException(500, "Base de connaissances introuvable (corpus_path mal configuré ?).")
    except QDRANT_ERRORS as exc:
        raise HTTPException(503, f"Index vectoriel indisponible : {exc}")


@router.post("/organizations/{org_id}/search", response_model=list[SearchResult])
def search(org_id: str, body: SearchRequest, db: Session = Depends(get_db)):
    if not db.get(Organization, org_id):
        raise HTTPException(404, "Organisation introuvable.")
    try:
        items = retrieval.hybrid_search(db, org_id, body.query, body.k, body.scope)
    except QDRANT_ERRORS as exc:
        raise HTTPException(503, f"Index vectoriel indisponible : {exc}")
    return [SearchResult(**item.__dict__) for item in items]

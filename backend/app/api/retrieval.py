from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization
from app.schemas import IndexReport, KbIndexReport, SearchRequest, SearchResult
from app.services import retrieval

router = APIRouter(prefix="/api", tags=["retrieval"])


@router.post("/organizations/{org_id}/index", response_model=IndexReport)
def index_organization(org_id: str, db: Session = Depends(get_db)):
    if not db.get(Organization, org_id):
        raise HTTPException(404, "Organisation introuvable.")
    try:
        return retrieval.index_organization(db, org_id)
    except ConnectionError as exc:
        raise HTTPException(503, f"Qdrant indisponible : {exc}")


@router.post("/kb/index", response_model=KbIndexReport)
def index_kb():
    try:
        return retrieval.index_kb()
    except FileNotFoundError:
        raise HTTPException(500, "Base de connaissances introuvable (corpus_path mal configuré ?).")


@router.post("/organizations/{org_id}/search", response_model=list[SearchResult])
def search(org_id: str, body: SearchRequest, db: Session = Depends(get_db)):
    if not db.get(Organization, org_id):
        raise HTTPException(404, "Organisation introuvable.")
    items = retrieval.hybrid_search(db, org_id, body.query, body.k, body.scope)
    return [SearchResult(**item.__dict__) for item in items]

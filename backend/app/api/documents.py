import hashlib

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Document, DocumentPage, DocumentStatus, Organization
from app.schemas import DocumentOut, DocumentPageOut
from app.services import qdrant
from app.services.parsing import (
    PARSER_VERSION,
    SUPPORTED_EXTENSIONS,
    EmptyDocument,
    InvalidEncoding,
    UnsupportedFileType,
    parse_document,
)

router = APIRouter(prefix="/api", tags=["documents"])

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


@router.post("/organizations/{org_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(org_id: str, file: UploadFile, db: Session = Depends(get_db)):
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organisation introuvable.")
    filename = file.filename or "document"
    if not any(filename.lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS):
        raise HTTPException(415, f"Type de fichier non supporté. Formats acceptés : {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(413, "Fichier trop volumineux (limite : 20 Mo).")

    checksum = hashlib.sha256(data).hexdigest()
    duplicate = db.scalar(
        select(Document).where(
            Document.organization_id == org_id, Document.checksum == checksum
        )
    )
    if duplicate:
        raise HTTPException(
            409, f"Document au contenu identique déjà téléversé : {duplicate.filename}"
        )

    doc = Document(
        organization_id=org_id,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        checksum=checksum,
        parser_version=PARSER_VERSION,
    )
    try:
        pages = parse_document(filename, data)
        doc.status = DocumentStatus.PARSED.value
        doc.page_count = len(pages)
        doc.pages = [DocumentPage(page_number=i + 1, text=text) for i, text in enumerate(pages)]
    except UnsupportedFileType as exc:
        raise HTTPException(415, str(exc))
    except (EmptyDocument, InvalidEncoding) as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        doc.status = DocumentStatus.FAILED.value
        doc.error = f"Échec de l'analyse : {exc}"

    db.add(doc)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent identical upload slipped past the pre-check; the DB
        # constraint (organization_id, checksum) is the atomic gate.
        db.rollback()
        raise HTTPException(409, "Document au contenu identique déjà téléversé.")
    return doc


@router.get("/organizations/{org_id}/documents", response_model=list[DocumentOut])
def list_documents(org_id: str, db: Session = Depends(get_db)):
    if not db.get(Organization, org_id):
        raise HTTPException(404, "Organisation introuvable.")
    return db.scalars(
        select(Document).where(Document.organization_id == org_id).order_by(Document.created_at)
    ).all()


@router.get("/documents/{document_id}/pages", response_model=list[DocumentPageOut])
def get_document_pages(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document introuvable.")
    return doc.pages


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document introuvable.")
    # Qdrant first: if it is unreachable we abort rather than leave orphan
    # vectors searchable. /index reconciliation is the recovery path.
    try:
        qdrant.delete_points_by_document(document_id)
    except Exception as exc:
        raise HTTPException(503, f"Index vectoriel indisponible, suppression annulée : {exc}")
    db.delete(doc)
    db.commit()

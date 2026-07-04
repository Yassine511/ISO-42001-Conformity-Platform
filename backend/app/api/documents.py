import hashlib

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Chunk, Document, DocumentPage, DocumentStatus, Finding, Organization
from app.schemas import DocumentOut, DocumentPageOut
from app.services import qdrant
from app.services.parsing import (
    PARSER_VERSION,
    SUPPORTED_EXTENSIONS,
    DocumentTooLarge,
    EmptyDocument,
    InvalidEncoding,
    UnsupportedFileType,
    parse_document,
)

router = APIRouter(prefix="/api", tags=["documents"])

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
_READ_CHUNK = 1024 * 1024  # 1 MB


async def _read_capped(file: UploadFile, cap: int) -> bytes:
    """Read the upload in chunks, aborting as soon as `cap` is exceeded.

    A Content-Length header is rejected earlier by middleware, but a chunked
    request may omit it — this bounds our own memory use to `cap` regardless of
    how much the multipart parser spooled to disk.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_READ_CHUNK):
        total += len(chunk)
        if total > cap:
            raise HTTPException(413, "Fichier trop volumineux (limite : 20 Mo).")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/organizations/{org_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(org_id: str, file: UploadFile, db: Session = Depends(get_db)):
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organisation introuvable.")
    filename = file.filename or "document"
    if not any(filename.lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS):
        raise HTTPException(415, f"Type de fichier non supporté. Formats acceptés : {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

    data = await _read_capped(file, MAX_FILE_SIZE)

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
    except DocumentTooLarge as exc:
        raise HTTPException(413, str(exc))
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
    # Audit-trail guard: refuse to delete a document a finding cites as evidence
    # (matched_chunk_id -> chunk -> this document). Cascading its pages/chunks
    # would leave that finding's citation dangling. Findings snapshot the cited
    # text in `retrieved`, but the live source that makes a citation clickable
    # must not silently disappear. Checked before Qdrant so a cited document is
    # never partially removed.
    cited = db.scalar(
        select(Finding.id)
        .join(Chunk, Finding.matched_chunk_id == Chunk.id)
        .where(Chunk.document_id == document_id)
        .limit(1)
    )
    if cited:
        raise HTTPException(
            409,
            "Suppression refusée : ce document est cité comme preuve par au moins "
            "un constat ; la supprimer romprait la traçabilité de la citation.",
        )
    # Qdrant first: if it is unreachable we abort rather than leave orphan
    # vectors searchable. /index reconciliation is the recovery path.
    try:
        qdrant.delete_points_by_document(document_id)
    except Exception as exc:
        raise HTTPException(503, f"Index vectoriel indisponible, suppression annulée : {exc}")
    db.delete(doc)
    db.commit()

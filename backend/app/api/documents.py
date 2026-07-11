import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Chunk,
    Document,
    DocumentPage,
    DocumentStatus,
    DocumentVersion,
    DocumentVersionEvent,
    Finding,
    Organization,
)
from app.schemas import DocumentOut, DocumentPageOut, DocumentVersionOut
from app.services.checksums import text_checksum
from app.services.chunking import CHUNKER_VERSION
from app.services import qdrant
from app.services.run_guard import RUNNING_CONFLICT_FR, lock_organization, running_assessment_id
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

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB — exact FILE limit, enforced by _read_capped
# The multipart envelope (boundary + part headers) makes the REQUEST larger than
# the file, so a request-level guard compared against MAX_FILE_SIZE would reject
# a valid ~20 MB file. Request-level caps (the Content-Length middleware and the
# nginx client_max_body_size) allow this margin; _read_capped still enforces the
# exact file size.
UPLOAD_REQUEST_MARGIN = 1 * 1024 * 1024  # 1 MB (request limit = MAX_FILE_SIZE + this)
_READ_CHUNK = 1024 * 1024  # 1 MB


def _canonical_format(filename: str) -> str:
    """Server-derived format from the (already validated) extension — the
    client-controlled multipart content_type is NEVER trusted for routing.
    txt and md are one parse/patch family but keep their own labels."""
    ext = filename.lower().rsplit(".", 1)[-1]
    return {"pdf": "pdf", "docx": "docx", "txt": "txt", "md": "md"}[ext]


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
    # Org row lock + RUNNING check: a document added mid-run would change what
    # later requirements retrieve, silently invalidating the assessment's
    # frozen document manifest.
    org = lock_organization(db, org_id)
    if not org:
        raise HTTPException(404, "Organisation introuvable.")
    if running_assessment_id(db, org_id):
        raise HTTPException(409, RUNNING_CONFLICT_FR)
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

    # Mirror columns (checksum/parser_version/page_count) are written only on
    # successful parse: a FAILED document has no version, no mirrors, and no
    # longer blocks re-upload of the same bytes (M7b behavior change).
    doc = Document(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
    )
    try:
        pages = parse_document(filename, data)
    except UnsupportedFileType as exc:
        raise HTTPException(415, str(exc))
    except DocumentTooLarge as exc:
        raise HTTPException(413, str(exc))
    except (EmptyDocument, InvalidEncoding) as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        doc.status = DocumentStatus.FAILED.value
        doc.error = f"Échec de l'analyse : {exc}"
    else:
        doc.status = DocumentStatus.PARSED.value
        doc.page_count = len(pages)
        doc.checksum = checksum
        doc.parser_version = PARSER_VERSION
        version = DocumentVersion(
            id=str(uuid.uuid4()),
            document_id=doc.id,
            organization_id=org_id,
            version_number=1,
            state="ACTIVE",  # authoritative content; Qdrant reconciled at /index
            source_checksum=checksum,
            text_checksum=text_checksum(pages),
            parser_version=PARSER_VERSION,
            chunker_version=CHUNKER_VERSION,
            chunk_id_scheme="version_id_v3",
            page_count=len(pages),
            origin="upload",
            canonical_format=_canonical_format(filename),
            filename=filename,
            reported_mime=file.content_type,
            byte_size=len(data),
        )
        version.pages = [
            DocumentPage(document_id=doc.id, page_number=i + 1, text=text)
            for i, text in enumerate(pages)
        ]
        doc.versions = [version]
        doc.current_version_id = version.id
        db.add(
            DocumentVersionEvent(
                document_id=doc.id,
                sequence=1,
                event_type="version_created",
                payload={
                    "version": 1,
                    "document_version_id": version.id,
                    "version_number": 1,
                    "origin": "upload",
                    "canonical_format": version.canonical_format,
                    "source_checksum": checksum,
                    "text_checksum": version.text_checksum,
                },
            )
        )

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
    """Pages of the CURRENT version (a failed document has none). Historical
    versions get their own endpoint in M7b commit 3."""
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document introuvable.")
    if doc.current_version_id is None:
        return []
    return db.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_version_id == doc.current_version_id)
        .order_by(DocumentPage.page_number)
    ).all()


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
def list_document_versions(document_id: str, db: Session = Depends(get_db)):
    if not db.get(Document, document_id):
        raise HTTPException(404, "Document introuvable.")
    return db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number, DocumentVersion.created_at)
    ).all()


def _get_version(db: Session, document_id: str, version_id: str) -> DocumentVersion:
    version = db.get(DocumentVersion, version_id)
    if not version or version.document_id != document_id:
        raise HTTPException(404, "Version de document introuvable.")
    return version


@router.get(
    "/documents/{document_id}/versions/{version_id}/pages",
    response_model=list[DocumentPageOut],
)
def get_version_pages(document_id: str, version_id: str, db: Session = Depends(get_db)):
    """Historical source inspection: the exact text a finding was made
    against, whatever the document's current version is."""
    _get_version(db, document_id, version_id)
    return db.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_version_id == version_id)
        .order_by(DocumentPage.page_number)
    ).all()


@router.get("/documents/{document_id}/versions/{version_id}/download")
def download_version(document_id: str, version_id: str, db: Session = Depends(get_db)):
    """TXT/MD only (PDF/DOCX bytes are never stored — only parsed text; a
    reconstructed file would be a lie). Patch-born versions are byte-faithful
    to their generated UTF-8 bytes; upload-born TXT/MD downloads are the
    parsed text re-encoded as UTF-8, which may differ byte-wise from a
    cp1252-encoded original."""
    version = _get_version(db, document_id, version_id)
    if version.canonical_format not in ("txt", "md"):
        raise HTTPException(
            409,
            "Téléchargement disponible uniquement pour les versions TXT/Markdown ; "
            "les originaux PDF/DOCX ne sont pas conservés sous forme de fichier.",
        )
    pages = db.scalars(
        select(DocumentPage)
        .where(DocumentPage.document_version_id == version_id)
        .order_by(DocumentPage.page_number)
    ).all()
    content = "".join(p.text for p in pages)  # TXT/MD parse to a single page
    media = "text/markdown" if version.canonical_format == "md" else "text/plain"
    safe_name = "".join(
        c for c in version.filename if c.isalnum() or c in "._- "
    ).strip() or f"version_{version.version_number}.{version.canonical_format}"
    return Response(
        content=content.encode("utf-8"),
        media_type=f"{media}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
        },
    )


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    # Lock the ORGANIZATION row first (consistent lock order with upload/index/
    # assessment creation), then the document row: the citation check and the
    # deletion are one atomic unit, and a deletion cannot race an assessment
    # launch that would retrieve from the vanishing document.
    peek = db.get(Document, document_id)
    if not peek:
        raise HTTPException(404, "Document introuvable.")
    lock_organization(db, peek.organization_id)
    if running_assessment_id(db, peek.organization_id):
        raise HTTPException(409, RUNNING_CONFLICT_FR)
    doc = db.get(Document, document_id, with_for_update=True)
    if not doc:  # deleted concurrently while we waited on the org lock
        raise HTTPException(404, "Document introuvable.")
    # Audit-trail guard: refuse to delete a document a finding cites as evidence
    # (matched_chunk_id -> chunk -> this document). Citation CONTENT is already
    # durable — findings snapshot the cited chunk's text/filename/page/offsets in
    # `retrieved`, which is by design how provenance survives (no FK on
    # matched_chunk_id: chunks are a rebuildable, re-indexable derived index, and
    # a RESTRICT FK would block the re-index that deletes stale chunks). This
    # guard additionally preserves the LIVE source so the citation stays
    # clickable; M4 chat citations render from the same snapshot. Checked before
    # Qdrant so a cited document is never partially removed.
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

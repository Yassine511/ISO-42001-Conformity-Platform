"""Test fixtures: deterministic fake embedder + in-memory Qdrant (autouse).

Tests never download the embedding model and never need a Qdrant container.
The fake embedder is a hashed bag-of-words: texts sharing words get similar
vectors, which is enough signal for retrieval-ranking tests.
"""

import hashlib
import math
import uuid

import pytest
from qdrant_client import QdrantClient

from app.services import embeddings, qdrant
from app.services.embeddings import EMBEDDING_DIM


def seed_parsed_document(
    db,
    org_id: str,
    filename: str,
    pages: list[str],
    *,
    checksum: str | None = None,
    content_type: str = "text/plain",
) -> "object":
    """Insert a parsed Document with its ACTIVE version-1 row + pages (M7b
    Document -> DocumentVersion -> pages shape). Commits; returns the Document.
    Mirrors the upload path so fixtures stay valid against sync_index."""
    from app.models import Document, DocumentPage, DocumentVersion
    from app.services.checksums import text_checksum
    from app.services.chunking import CHUNKER_VERSION
    from app.services.parsing import PARSER_VERSION

    source = checksum or hashlib.sha256(
        "\n".join(pages).encode("utf-8")
    ).hexdigest()
    doc = Document(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        filename=filename,
        content_type=content_type,
        status="parsed",
        page_count=len(pages),
        checksum=source,
        parser_version=PARSER_VERSION,
    )
    version = DocumentVersion(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        organization_id=org_id,
        version_number=1,
        state="ACTIVE",
        source_checksum=source,
        text_checksum=text_checksum(pages),
        parser_version=PARSER_VERSION,
        chunker_version=CHUNKER_VERSION,
        chunk_id_scheme="version_id_v3",
        page_count=len(pages),
        origin="upload",
        canonical_format=filename.lower().rsplit(".", 1)[-1],
        filename=filename,
    )
    version.pages = [
        DocumentPage(document_id=doc.id, page_number=i + 1, text=text)
        for i, text in enumerate(pages)
    ]
    doc.versions = [version]
    doc.current_version_id = version.id
    db.add(doc)
    db.commit()
    return doc


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        v = [0.0] * EMBEDDING_DIM
        for token in text.casefold().split():
            slot = int(hashlib.md5(token.encode()).hexdigest(), 16) % EMBEDDING_DIM
            v[slot] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]


@pytest.fixture(autouse=True)
def fake_vector_stack():
    embeddings.set_provider(FakeEmbedder())
    qdrant.set_client(QdrantClient(":memory:"))
    yield
    embeddings.set_provider(None)
    qdrant.set_client(None)

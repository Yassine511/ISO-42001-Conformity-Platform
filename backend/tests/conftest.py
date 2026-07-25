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
    db.add(doc)
    # Two steps, like the real activation transaction: the composite FK
    # fk_documents_current_version proves (id, current_version_id) names a
    # version OF THIS document, so the pointer can only be set once the version
    # row exists. Setting it in the same INSERT passed only while the test
    # schema was missing that constraint (see test_migration_head_matches_
    # the_models) — production PostgreSQL always refused it.
    db.flush()
    doc.current_version_id = version.id
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
def reset_rate_limiters():
    """The auth limiters are module-level process state. Without this, a test
    that exhausts a window makes an unrelated later test 429 — and the order
    dependence would only show up in CI."""
    from app.services import rate_limit

    rate_limit.login_limiter.clear()
    rate_limit.signup_limiter.clear()
    yield
    rate_limit.login_limiter.clear()
    rate_limit.signup_limiter.clear()


@pytest.fixture(autouse=True)
def fake_vector_stack():
    embeddings.set_provider(FakeEmbedder())
    qdrant.set_client(QdrantClient(":memory:"))
    yield
    embeddings.set_provider(None)
    qdrant.set_client(None)


# --- M10 auth bypass -------------------------------------------------------
# Pre-M10 tests exercise business routes without authenticating. The autouse
# override injects a stub current user; because POST /api/organizations now
# grants the creator a membership row (user_id = this stub's id), every test
# that creates its org through the API passes the membership guard unchanged.
# SQLite tests run with FKs off, so the stub needs no users row. Tests that
# seed an Organization row directly in the DB call seed_membership(db, org_id).
# tests/test_auth.py removes the override to exercise the real login flow.

TEST_USER_ID = "00000000-0000-0000-0000-0000000000aa"


def seed_membership(db, org_id: str) -> None:
    from app.models import OrganizationMember

    db.add(OrganizationMember(organization_id=org_id, user_id=TEST_USER_ID))
    db.commit()


@pytest.fixture(autouse=True)
def bypass_auth():
    from app.api.deps import get_current_user
    from app.main import app
    from app.models import User

    stub = User(
        id=TEST_USER_ID,
        email="test@int102.local",
        password_hash="!",
        display_name="Test harness",
    )
    app.dependency_overrides[get_current_user] = lambda: stub
    yield
    app.dependency_overrides.pop(get_current_user, None)

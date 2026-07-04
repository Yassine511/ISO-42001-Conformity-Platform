import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # No context manager: skips lifespan (which would hit Postgres); tables are created above.
    tc = TestClient(app)
    tc.session_factory = TestSession  # tests needing direct DB setup use this
    yield tc
    app.dependency_overrides.clear()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["database"] == "ok"


def test_org_and_document_flow(client):
    r = client.post("/api/organizations", json={"name": "Lumen AI"})
    assert r.status_code == 201
    org_id = r.json()["id"]

    # duplicate name rejected
    assert client.post("/api/organizations", json={"name": "Lumen AI"}).status_code == 409

    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique_ia.txt", "Les systèmes d'IA sont inventoriés.".encode(), "text/plain")},
    )
    assert r.status_code == 201
    doc = r.json()
    assert doc["status"] == "parsed"
    assert doc["page_count"] == 1

    pages = client.get(f"/api/documents/{doc['id']}/pages").json()
    assert "inventoriés" in pages[0]["text"]

    docs = client.get(f"/api/organizations/{org_id}/documents").json()
    assert len(docs) == 1

    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    assert client.get(f"/api/organizations/{org_id}/documents").json() == []


def test_unsupported_upload(client):
    org_id = client.post("/api/organizations", json={"name": "X"}).json()["id"]
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("image.png", b"\x89PNG", "image/png")},
    )
    assert r.status_code == 415


def test_blank_organization_name_rejected(client):
    assert client.post("/api/organizations", json={"name": "   "}).status_code == 422
    assert client.post("/api/organizations", json={"name": ""}).status_code == 422


def test_empty_document_rejected(client):
    org_id = client.post("/api/organizations", json={"name": "Vide SA"}).json()["id"]
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("vide.txt", b"   ", "text/plain")},
    )
    assert r.status_code == 422
    # nothing persisted
    assert client.get(f"/api/organizations/{org_id}/documents").json() == []


def test_document_has_checksum_and_parser_version(client):
    import hashlib

    org_id = client.post("/api/organizations", json={"name": "Hash SA"}).json()["id"]
    data = "Contenu de politique IA.".encode()
    doc = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("p.txt", data, "text/plain")},
    ).json()
    assert doc["checksum"] == hashlib.sha256(data).hexdigest()
    assert doc["parser_version"]


def test_oversized_upload_rejected(client, monkeypatch):
    """An upload whose request size exceeds the request-level cap is rejected 413
    (limits shrunk for the test)."""
    import app.api.documents as docs_mod

    monkeypatch.setattr(docs_mod, "MAX_FILE_SIZE", 50)
    monkeypatch.setattr(docs_mod, "UPLOAD_REQUEST_MARGIN", 0)
    org_id = client.post("/api/organizations", json={"name": "Big SA"}).json()["id"]
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("big.txt", b"A" * 500, "text/plain")},
    )
    assert r.status_code == 413
    assert client.get(f"/api/organizations/{org_id}/documents").json() == []


def test_valid_upload_near_limit_not_rejected_for_overhead(client, monkeypatch):
    """Regression (finding): the request-level guard must NOT reject a valid file
    just because multipart framing pushes the whole request over the FILE limit.
    Reproduces the reported 1000-byte cap / 850-byte file case — now accepted,
    since the guard compares against the request-size limit (file + margin)."""
    import app.api.documents as docs_mod

    monkeypatch.setattr(docs_mod, "MAX_FILE_SIZE", 1000)  # margin (~1 MB) unchanged
    org_id = client.post("/api/organizations", json={"name": "Near SA"}).json()["id"]
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("ok.txt", b"A" * 850, "text/plain")},
    )
    assert r.status_code == 201


def test_cited_document_cannot_be_deleted(client):
    """Audit-trail guard: a document cited by a finding must not be deletable —
    its removal would leave the citation dangling."""
    from app.models import Assessment, Chunk, Document, DocumentPage, Finding, Organization

    db = client.session_factory()
    org = Organization(name="Cite SA")
    db.add(org)
    db.commit()
    doc = Document(
        organization_id=org.id,
        filename="p.txt",
        content_type="text/plain",
        status="parsed",
        page_count=1,
        checksum="c1",
        parser_version="2",
    )
    db.add(doc)
    db.commit()
    db.add(DocumentPage(document_id=doc.id, page_number=1, text="x" * 50))
    db.add(
        Chunk(
            id="chunk-cite-1",
            document_id=doc.id,
            page_number=1,
            char_start=0,
            char_end=10,
            text="x" * 10,
        )
    )
    assessment = Assessment(organization_id=org.id, corpus_version="1.0.0", status="RUNNING")
    db.add(assessment)
    db.commit()
    db.add(
        Finding(
            assessment_id=assessment.id,
            requirement_id="A.9.2",
            status="VERIFIED",
            matched_chunk_id="chunk-cite-1",
            attempts=1,
        )
    )
    db.commit()
    org_id, doc_id = org.id, doc.id
    db.close()

    assert client.delete(f"/api/documents/{doc_id}").status_code == 409
    # still present: the guard fired before any deletion
    assert len(client.get(f"/api/organizations/{org_id}/documents").json()) == 1

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
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


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

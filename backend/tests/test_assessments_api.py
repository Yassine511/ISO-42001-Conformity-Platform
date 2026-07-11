"""HTTP-level tests for the M5 assessment run API.

runner.launch is stubbed to a no-op recorder in the client fixture: endpoint
tests exercise creation/guards/read models without cross-thread SQLite use;
the run loop itself is covered synchronously in tests/test_runner.py.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import assessments as assessments_api
from app.db import Base, get_db
from app.main import app
from app.models import Assessment, Document
from app.pipeline import llm as llm_service
from app.pipeline import runner
from app.pipeline.dev_split import DEV_REQUIREMENT_IDS, DEV_SPLIT_CORPUS_VERSION
from app.services.chunking import CHUNKER_VERSION
from app.services.retrieval import load_kb
from tests.test_pipeline import DOC_TEXT, FakeLLM, _valid_draft

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(monkeypatch):
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

    launched: list[str] = []
    monkeypatch.setattr(runner, "launch", lambda sf, aid: launched.append(aid) or True)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[assessments_api.get_session_factory] = lambda: TestSession
    tc = TestClient(app)
    tc.session_factory = TestSession
    tc.launched = launched
    yield tc
    app.dependency_overrides.clear()
    llm_service.set_provider(None)


def _make_org(client, name="Lumen AI") -> str:
    org_id = client.post("/api/organizations", json={"name": name}).json()["id"]
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique_ia.txt", DOC_TEXT.encode(), "text/plain")},
    )
    assert r.status_code == 201
    return org_id


def _test_split_id() -> str:
    """Any KB id outside the dev split (holdout membership: test-only info)."""
    kb = load_kb()
    dev = set(DEV_REQUIREMENT_IDS)
    return next(rid for rid in kb["by_id"] if rid not in dev)


# ---------------------------------------------------------------- creation


def test_create_freezes_run_contract_and_launches(client):
    org_id = _make_org(client)
    r = client.post(
        f"/api/organizations/{org_id}/assessments",
        json={"requirement_ids": ["A.9.2", "A.4.5"], "k": 4},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "RUNNING"
    assert body["requirement_ids"] == ["A.9.2", "A.4.5"]
    assert body["retrieval_k"] == 4
    assert body["cancel_requested"] is False
    assert body["manifest_complete"] is True
    assert body["total"] == 2 and body["findings_done"] == 0
    manifest = body["document_manifest"]
    assert manifest["chunk_count"] > 0
    assert manifest["indexed_at"]
    assert [d["filename"] for d in manifest["documents"]] == ["politique_ia.txt"]
    entry = manifest["documents"][0]
    assert entry["checksum"]
    # M7b: provenance is per document VERSION (no global chunker claim)
    assert "chunker_version" not in manifest
    assert entry["document_version_id"]
    assert entry["version_number"] == 1
    assert entry["chunker_version"] == CHUNKER_VERSION
    assert entry["chunk_id_scheme"] == "version_id_v3"
    assert entry["text_checksum"] and entry["source_checksum"] == entry["checksum"]
    assert client.launched == [body["id"]]
    # auto-index actually ran: chunks exist in PG
    db = client.session_factory()
    from app.models import Chunk

    assert db.scalars(select(Chunk)).first() is not None
    db.close()


def test_create_defaults_to_frozen_dev_manifest(client):
    org_id = _make_org(client)
    r = client.post(f"/api/organizations/{org_id}/assessments", json={})
    assert r.status_code == 202
    assert r.json()["requirement_ids"] == DEV_REQUIREMENT_IDS
    assert r.json()["total"] == 51


def test_create_validation_errors(client):
    org_id = _make_org(client)
    # unknown org
    assert client.post("/api/organizations/nope/assessments", json={}).status_code == 404
    # empty manifest
    r = client.post(
        f"/api/organizations/{org_id}/assessments", json={"requirement_ids": []}
    )
    assert r.status_code == 422 and "manifeste vide" in r.json()["detail"]
    # duplicates rejected
    r = client.post(
        f"/api/organizations/{org_id}/assessments",
        json={"requirement_ids": ["A.9.2", "A.9.2"]},
    )
    assert r.status_code == 422 and "double" in r.json()["detail"]
    # unknown id
    r = client.post(
        f"/api/organizations/{org_id}/assessments", json={"requirement_ids": ["NOPE.1"]}
    )
    assert r.status_code == 422 and "inconnue" in r.json()["detail"]
    # k out of bounds -> French normalized Pydantic error
    r = client.post(f"/api/organizations/{org_id}/assessments", json={"k": 99})
    assert r.status_code == 422 and r.json()["detail"].startswith("Requête invalide")


def test_create_rejects_m6_holdout_ids(client):
    """Backend-enforced holdout protection: the API cannot run a test-split
    requirement even when asked explicitly."""
    org_id = _make_org(client)
    held_out = _test_split_id()
    r = client.post(
        f"/api/organizations/{org_id}/assessments",
        json={"requirement_ids": ["A.9.2", held_out]},
    )
    assert r.status_code == 422
    assert "réservée" in r.json()["detail"] and held_out in r.json()["detail"]


def test_create_requires_a_parsed_document(client):
    org_id = client.post("/api/organizations", json={"name": "Sans docs"}).json()["id"]
    r = client.post(f"/api/organizations/{org_id}/assessments", json={})
    assert r.status_code == 422
    assert "aucun document" in r.json()["detail"]


def test_create_conflicts_while_running(client):
    org_id = _make_org(client)
    assert (
        client.post(f"/api/organizations/{org_id}/assessments", json={}).status_code == 202
    )
    r = client.post(f"/api/organizations/{org_id}/assessments", json={})
    assert r.status_code == 409
    assert r.json()["detail"] == assessments_api.ALREADY_RUNNING_FR


def test_create_maps_integrity_error_to_409(client, monkeypatch):
    """The DB partial unique index is the concurrency backstop: when the
    friendly pre-check races and the INSERT hits the index, the API must
    still answer 409, not 500."""
    org_id = _make_org(client)

    def raise_integrity(*args, **kwargs):
        raise IntegrityError("INSERT INTO assessments", {}, Exception("uq_assessments_one_running"))

    monkeypatch.setattr(assessments_api, "create_assessment", raise_integrity)
    r = client.post(f"/api/organizations/{org_id}/assessments", json={})
    assert r.status_code == 409
    assert r.json()["detail"] == assessments_api.ALREADY_RUNNING_FR


# ---------------------------------------------------------------- reads


def test_list_and_detail_are_org_scoped(client):
    org_a = _make_org(client, "Org A")
    org_b = _make_org(client, "Org B")
    aid = client.post(f"/api/organizations/{org_a}/assessments", json={}).json()["id"]

    listing_b = client.get(f"/api/organizations/{org_b}/assessments").json()
    assert listing_b == []
    assert (
        client.get(f"/api/organizations/{org_b}/assessments/{aid}").status_code == 404
    )
    detail = client.get(f"/api/organizations/{org_a}/assessments/{aid}")
    assert detail.status_code == 200
    assert detail.json()["findings"] == []
    assert detail.json()["cancel_requested"] is False


# ---------------------------------------------------------------- lifecycle


def test_resume_refuses_terminal_and_legacy_rows(client):
    org_id = _make_org(client)
    db = client.session_factory()
    completed = Assessment(
        organization_id=org_id,
        corpus_version="1.2.0",
        status="COMPLETED",
        requirement_ids=["A.9.2"],
        document_manifest={"documents": []},
    )
    legacy = Assessment(
        organization_id=org_id,
        corpus_version="1.2.0",
        status="RUNNING",
        requirement_ids=["A.9.2"],
        document_manifest=None,  # pre-M5 row
    )
    db.add_all([completed, legacy])
    db.commit()
    cid, lid = completed.id, legacy.id
    db.close()

    r = client.post(f"/api/organizations/{org_id}/assessments/{cid}/resume")
    assert r.status_code == 409
    r = client.post(f"/api/organizations/{org_id}/assessments/{lid}/resume")
    assert r.status_code == 422 and "manifeste incomplet" in r.json()["detail"]


def test_abandon_orphan_finalizes_failed(client):
    org_id = _make_org(client)
    aid = client.post(f"/api/organizations/{org_id}/assessments", json={}).json()["id"]
    # no live in-process thread (launch is stubbed) -> orphan recovery path
    r = client.post(f"/api/organizations/{org_id}/assessments/{aid}/abandon")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "FAILED"
    assert body["error"] == "Abandonnée par l'utilisateur."
    # terminal metadata is canonical: the request flag is cleared on
    # finalization — the cancellation is recorded in error/status
    assert body["cancel_requested"] is False
    # a terminal assessment cannot be abandoned again
    r = client.post(f"/api/organizations/{org_id}/assessments/{aid}/abandon")
    assert r.status_code == 409


# ------------------------------------------------- corpus mutation guards


def test_corpus_mutations_blocked_while_running(client):
    org_id = _make_org(client)
    db = client.session_factory()
    doc_id = db.scalars(select(Document.id)).first()
    db.close()
    client.post(f"/api/organizations/{org_id}/assessments", json={})

    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("autre.txt", "Nouvelle politique.".encode(), "text/plain")},
    )
    assert r.status_code == 409 and "évaluation est en cours" in r.json()["detail"]
    r = client.delete(f"/api/documents/{doc_id}")
    assert r.status_code == 409 and "évaluation est en cours" in r.json()["detail"]
    r = client.post(f"/api/organizations/{org_id}/index")
    assert r.status_code == 409 and "évaluation est en cours" in r.json()["detail"]


# ---------------------------------------------------------------- KB + split


def test_kb_requirements_exposes_only_dev_split(client):
    r = client.get("/api/kb/requirements")
    assert r.status_code == 200
    body = r.json()
    assert [e["id"] for e in body] == DEV_REQUIREMENT_IDS
    assert len(body) == 51
    assert all(e["requirement_fr"] for e in body)


def test_frozen_dev_split_matches_gold_labels():
    """Test-only gold read: the frozen runtime manifest must equal the gold
    dev split exactly (order included) so it cannot silently drift."""
    gold = json.loads(
        (REPO_ROOT / "corpus" / "gold" / "gold_labels.json").read_text(encoding="utf-8")
    )
    dev = [i["requirement_id"] for i in gold["items"] if i["split"] == "dev"]
    assert DEV_REQUIREMENT_IDS == dev
    assert gold["meta"]["corpus_version"] == DEV_SPLIT_CORPUS_VERSION
    held_out = [i["requirement_id"] for i in gold["items"] if i["split"] != "dev"]
    assert len(held_out) == 14
    assert not set(held_out) & set(DEV_REQUIREMENT_IDS)

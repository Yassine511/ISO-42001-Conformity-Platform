"""M7b version-aware retrieval + upload lifecycle.

Snapshot-consistent hybrid search (stale versions never surface in either
arm; mid-search activation retries the whole attempt once then raises the
typed conflict), reconciliation that preserves history and recoverable
candidates, and the version endpoints.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import get_db
from app.main import app as fastapi_app
from app.models import Chunk, Document, DocumentPage, DocumentVersion
from app.services import qdrant as qdrant_service
from app.services.checksums import text_checksum
from app.services.chunking import CHUNKER_VERSION
from app.services.embeddings import embed_texts
from app.services.parsing import PARSER_VERSION
from app.services.retrieval import _chunk_point, materialize_version_chunks

# The API test client fixture (SQLite override) lives in test_api.py
from tests.test_api import client  # noqa: F401
from tests.test_retrieval import DOC_A, DOC_B, _setup_org  # noqa: F401

NEW_TEXT = (
    "Politique de gouvernance des données révisée.\n\n"
    "La provenance des données d'entraînement est enregistrée et revue chaque mois."
)


def _db():
    return next(fastapi_app.dependency_overrides[get_db]())


def _make_version(db, doc, pages: list[str], number: int, supersedes: str, *, index_points=True):
    """Insert a PENDING_INDEX candidate with materialized + indexed chunks."""
    version = DocumentVersion(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        organization_id=doc.organization_id,
        version_number=number,
        state="PENDING_INDEX",
        source_checksum="src-" + str(uuid.uuid4())[:8],
        text_checksum=text_checksum(pages),
        parser_version=PARSER_VERSION,
        chunker_version=CHUNKER_VERSION,
        chunk_id_scheme="version_id_v3",
        page_count=len(pages),
        origin="patch",
        supersedes_version_id=supersedes,
        canonical_format="txt",
        filename=doc.filename,
        byte_size=sum(len(p.encode()) for p in pages),
        activation_token=str(uuid.uuid4()),
        activation_started_at=datetime.now(timezone.utc),
        activation_heartbeat_at=datetime.now(timezone.utc),
    )
    version.pages = [
        DocumentPage(document_id=doc.id, page_number=i + 1, text=t)
        for i, t in enumerate(pages)
    ]
    db.add(version)
    db.commit()
    rows = materialize_version_chunks(db, version)
    db.commit()
    if index_points:
        qdrant_service.ensure_collection()
        vectors = embed_texts([r.text for r in rows])
        qdrant_service.upsert_points(
            [_chunk_point(r, doc.organization_id, v) for r, v in zip(rows, vectors)]
        )
    return version, rows


def _activate_new_version(doc_id: str, pages: list[str]) -> str:
    """Simulate a completed activation: new version indexed, pointer flipped,
    old version SUPERSEDED — old Qdrant points deliberately left behind (the
    post-commit cleanup is allowed to fail; snapshot filtering + hydration
    are the correctness layer)."""
    db = _db()
    doc = db.get(Document, doc_id)
    base = db.get(DocumentVersion, doc.current_version_id)
    version, _rows = _make_version(db, doc, pages, base.version_number + 1, base.id)
    base.state = "SUPERSEDED"
    db.flush()
    version.state = "ACTIVE"
    version.activation_token = None
    version.activation_started_at = None
    version.activation_heartbeat_at = None
    doc.current_version_id = version.id
    doc.checksum = version.source_checksum
    db.commit()
    return version.id


def test_stale_version_never_surfaces_in_either_arm(client):
    """Vector arm (snapshot MatchAny), BM25 arm (snapshot ids) and hydration
    all exclude superseded-version chunks even when their points remain in
    Qdrant and their text matches the query better than the current one."""
    org_id, docs = _setup_org(client)
    client.post(f"/api/organizations/{org_id}/index")
    new_vid = _activate_new_version(docs["data.txt"], [NEW_TEXT])

    r = client.post(
        f"/api/organizations/{org_id}/search",
        # phrased to match the OLD v1 text best ("fiche d'acquisition validée")
        json={"query": "fiche d'acquisition validée provenance données", "k": 6},
    )
    assert r.status_code == 200
    db = _db()
    hits_for_doc = [i for i in r.json() if i["document_id"] == docs["data.txt"]]
    assert hits_for_doc, "current version must still be retrievable"
    for item in hits_for_doc:
        chunk = db.get(Chunk, item["result_id"])
        assert chunk.document_version_id == new_vid, "a superseded chunk surfaced"


def test_index_preserves_history_and_reaps_stale_points(client):
    """/index never deletes historical PG chunk rows (finding provenance) but
    does reap the superseded version's Qdrant points; recoverable candidate
    points survive reconciliation and never surface in search."""
    org_id, docs = _setup_org(client)
    client.post(f"/api/organizations/{org_id}/index")

    db = _db()
    doc = db.get(Document, docs["data.txt"])
    old_vid = doc.current_version_id
    old_chunk_ids = set(
        db.scalars(select(Chunk.id).where(Chunk.document_version_id == old_vid)).all()
    )
    assert old_chunk_ids

    new_vid = _activate_new_version(docs["data.txt"], [NEW_TEXT])
    db = _db()
    doc = db.get(Document, docs["data.txt"])
    cand, cand_rows = _make_version(
        db, doc, ["Texte candidat en attente."], 3, new_vid
    )
    cand_point_keys = {qdrant_service.point_id(r.id) for r in cand_rows}
    old_point_keys = {qdrant_service.point_id(cid) for cid in old_chunk_ids}

    report = client.post(f"/api/organizations/{org_id}/index").json()
    assert report["documents"] == 2

    still = set(
        db.scalars(select(Chunk.id).where(Chunk.document_version_id == old_vid)).all()
    )
    assert still == old_chunk_ids, "/index deleted historical chunk rows"

    from app.services.retrieval import _scroll_org_points

    remaining = {canonical for canonical, _ in _scroll_org_points(org_id).values()}
    assert not (old_point_keys & remaining), "superseded points not reaped"
    assert cand_point_keys <= remaining, "recoverable candidate points were reaped"

    r = client.post(
        f"/api/organizations/{org_id}/search",
        json={"query": "texte candidat en attente", "k": 6},
    )
    for item in r.json():
        chunk = db.get(Chunk, item["result_id"])
        assert chunk.document_version_id != cand.id, "pending candidate surfaced"


def test_snapshot_flip_retries_whole_search_then_conflicts(client, monkeypatch):
    """One mid-search pointer flip => the entire hybrid attempt (vector, BM25,
    RRF, hydration) is retried with the fresh snapshot; a second flip raises
    the typed retryable conflict (HTTP 409) — snapshots are never mixed."""
    org_id, _docs = _setup_org(client)
    client.post(f"/api/organizations/{org_id}/index")

    from app.services import retrieval as retrieval_mod

    real = retrieval_mod._current_snapshot
    calls = {"n": 0}

    def flip_once(db, oid):
        calls["n"] += 1
        snap = dict(real(db, oid))
        if calls["n"] == 2:  # attempt 1's consistency check sees a flip
            snap[next(iter(snap))] = "flipped-version-id"
        return snap

    monkeypatch.setattr(retrieval_mod, "_current_snapshot", flip_once)
    r = client.post(
        f"/api/organizations/{org_id}/search",
        json={"query": "provenance des données", "k": 3},
    )
    assert r.status_code == 200 and r.json()
    assert calls["n"] == 4  # attempt1 + check, attempt2 + check

    calls["n"] = 0

    def always_flipping(db, oid):
        calls["n"] += 1
        snap = dict(real(db, oid))
        snap[next(iter(snap))] = f"flip-{calls['n']}"
        return snap

    monkeypatch.setattr(retrieval_mod, "_current_snapshot", always_flipping)
    r = client.post(
        f"/api/organizations/{org_id}/search",
        json={"query": "provenance des données", "k": 3},
    )
    assert r.status_code == 409
    assert "modifié" in r.json()["detail"]


def test_empty_snapshot_returns_no_policy_candidates(client):
    """An org with no parsed documents: the policy vector arm must not send
    an empty MatchAny to Qdrant — the search simply returns nothing."""
    org_id = client.post("/api/organizations", json={"name": "Vide SA"}).json()["id"]
    r = client.post(
        f"/api/organizations/{org_id}/search",
        json={"query": "provenance des données", "k": 3},
    )
    assert r.status_code == 200 and r.json() == []


def test_version_endpoints_list_pages_download(client):
    """GET /versions, /versions/{vid}/pages (historical text), and /download
    (TXT/MD only, UTF-8; PDF/DOCX refused)."""
    org_id, docs = _setup_org(client)
    doc_id = docs["data.txt"]
    db = _db()
    old_vid = db.get(Document, doc_id).current_version_id
    new_vid = _activate_new_version(doc_id, [NEW_TEXT])

    versions = client.get(f"/api/documents/{doc_id}/versions").json()
    assert [v["version_number"] for v in versions] == [1, 2]
    assert versions[0]["state"] == "SUPERSEDED" and versions[1]["state"] == "ACTIVE"
    assert versions[1]["supersedes_version_id"] == old_vid

    # current pages endpoint serves v2; historical endpoint still serves v1
    current = client.get(f"/api/documents/{doc_id}/pages").json()
    assert current[0]["text"] == NEW_TEXT
    historical = client.get(f"/api/documents/{doc_id}/versions/{old_vid}/pages").json()
    assert historical[0]["text"] == DOC_A

    r = client.get(f"/api/documents/{doc_id}/versions/{new_vid}/download")
    assert r.status_code == 200
    assert r.content.decode("utf-8") == NEW_TEXT
    assert "attachment" in r.headers["content-disposition"]

    # a PDF version cannot be downloaded (bytes were never stored)
    version = db.get(DocumentVersion, new_vid)
    version.canonical_format = "pdf"
    db.commit()
    r = client.get(f"/api/documents/{doc_id}/versions/{new_vid}/download")
    assert r.status_code == 409

    # unknown / cross-document version ids are 404
    other_doc = docs["lifecycle.txt"]
    r = client.get(f"/api/documents/{other_doc}/versions/{new_vid}/pages")
    assert r.status_code == 404

from app.services.bm25 import Bm25Index, analyze

# The API test client fixture (SQLite override) lives in test_api.py
from tests.test_api import client  # noqa: F401


# ---------------------------------------------------------------- analyzer / BM25


def test_analyzer_stems_and_strips_accents():
    a = analyze("données d'entraînement")
    b = analyze("donnée entraînée")
    assert set(a) & set(b), f"no shared stems between {a} and {b}"


def test_analyzer_drops_stopwords():
    tokens = analyze("la politique de l'IA et des données")
    assert "la" not in tokens and "de" not in tokens and "et" not in tokens


def test_bm25_ranks_relevant_first():
    idx = Bm25Index(
        [
            ("c1", "La provenance des données d'entraînement est documentée."),
            ("c2", "Le déploiement des modèles suit un plan standard."),
            ("c3", "Les fournisseurs font l'objet d'une due diligence."),
        ]
    )
    hits = idx.search("provenance des données", k=3)
    assert hits and hits[0][0] == "c1"


def test_bm25_empty_corpus_and_stopword_query():
    assert Bm25Index([]).search("données", 5) == []
    idx = Bm25Index([("c1", "texte quelconque")])
    assert idx.search("le la de", 5) == []  # all stopwords -> no tokens


# ---------------------------------------------------------------- end-to-end API

DOC_A = (
    "Politique de gouvernance des données.\n\n"
    "La provenance des données d'entraînement est enregistrée dans le registre dédié.\n\n"
    "Chaque jeu de données possède une fiche d'acquisition validée."
)
DOC_B = (
    "Politique de cycle de vie des modèles.\n\n"
    "Le déploiement des systèmes suit le plan de mise en production standard.\n\n"
    "Les journaux d'événements sont conservés trente jours."
)


def _setup_org(client):
    org_id = client.post("/api/organizations", json={"name": "RAG Test"}).json()["id"]
    docs = {}
    for name, content in [("data.txt", DOC_A), ("lifecycle.txt", DOC_B)]:
        r = client.post(
            f"/api/organizations/{org_id}/documents",
            files={"file": (name, content.encode(), "text/plain")},
        )
        assert r.status_code == 201, r.text
        docs[name] = r.json()["id"]
    return org_id, docs


def test_index_and_search_policy(client):
    org_id, docs = _setup_org(client)

    report = client.post(f"/api/organizations/{org_id}/index").json()
    assert report["documents"] == 2 and report["chunks"] >= 2 and report["added"] == report["chunks"]

    # reindex is idempotent
    report2 = client.post(f"/api/organizations/{org_id}/index").json()
    assert report2["added"] == 0 and report2["removed"] == 0

    r = client.post(
        f"/api/organizations/{org_id}/search",
        json={"query": "provenance des données d'entraînement", "k": 3},
    )
    assert r.status_code == 200
    results = r.json()
    assert results, "no results"
    top = results[0]
    assert top["source_type"] == "policy"
    assert top["document_id"] == docs["data.txt"]
    assert "provenance" in top["text"]
    assert top["vector_rank"] is not None or top["bm25_rank"] is not None

    # provenance offsets slice the stored page exactly
    pages = client.get(f"/api/documents/{docs['data.txt']}/pages").json()
    page_text = pages[top["page_number"] - 1]["text"]
    assert page_text[top["char_start"] : top["char_end"]] == top["text"]


def test_kb_index_and_scope(client):
    org_id, _ = _setup_org(client)
    kb_report = client.post("/api/kb/index").json()
    assert kb_report["requirements"] == 65

    r = client.post(
        f"/api/organizations/{org_id}/search",
        json={"query": "provenance des données", "k": 5, "scope": "kb"},
    )
    results = r.json()
    assert results and all(x["source_type"] == "iso_requirement" for x in results)
    assert any(x["requirement_id"] == "A.7.5" for x in results)


def test_search_validation_bounds(client):
    org_id, _ = _setup_org(client)
    url = f"/api/organizations/{org_id}/search"
    assert client.post(url, json={"query": "   "}).status_code == 422
    assert client.post(url, json={"query": "x", "k": 0}).status_code == 422
    assert client.post(url, json={"query": "x", "k": 51}).status_code == 422


def test_delete_document_removes_vectors(client):
    org_id, docs = _setup_org(client)
    client.post(f"/api/organizations/{org_id}/index")

    assert client.delete(f"/api/documents/{docs['data.txt']}").status_code == 204
    r = client.post(
        f"/api/organizations/{org_id}/search",
        json={"query": "provenance des données d'entraînement", "k": 5},
    )
    assert all(x["document_id"] != docs["data.txt"] for x in r.json())


def test_delete_returns_503_when_qdrant_down(client, monkeypatch):
    org_id, docs = _setup_org(client)

    from app.api import documents as documents_api

    def boom(document_id):
        raise ConnectionError("qdrant down")

    monkeypatch.setattr(documents_api.qdrant, "delete_points_by_document", boom)
    r = client.delete(f"/api/documents/{docs['data.txt']}")
    assert r.status_code == 503
    # document must still exist (no orphan vectors)
    assert client.get(f"/api/documents/{docs['data.txt']}/pages").status_code == 200


def test_orphan_vector_discarded(client):
    """A Qdrant point unknown to PG must never surface in results."""
    org_id, _ = _setup_org(client)
    client.post(f"/api/organizations/{org_id}/index")

    from qdrant_client import models as qm

    from app.config import settings
    from app.services import embeddings as emb
    from app.services import qdrant as q

    rogue_vec = emb.embed_texts(["provenance des données d'entraînement"])[0]
    q.get_client().upsert(
        collection_name=settings.qdrant_collection,
        points=[
            qm.PointStruct(
                id=q.point_id("rogue-chunk-id"),
                vector=rogue_vec,
                payload={"source_type": "policy", "result_id": "rogue-chunk-id", "org_id": org_id},
            )
        ],
        wait=True,
    )
    r = client.post(
        f"/api/organizations/{org_id}/search",
        json={"query": "provenance des données d'entraînement", "k": 5},
    )
    assert all(x["result_id"] != "rogue-chunk-id" for x in r.json())


def test_qdrant_helpers_smoke():
    from app.services import qdrant as q

    q.ensure_collection()
    q.ensure_collection()  # idempotent
    q.delete_points_by_ids([q.point_id("whatever")])  # must not raise
    q.delete_points_by_document("no-such-doc")  # must not raise

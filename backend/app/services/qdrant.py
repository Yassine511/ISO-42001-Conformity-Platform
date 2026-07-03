"""Qdrant access: singleton client, collection lifecycle guard, point helpers.

PostgreSQL (policy chunks) and the versioned KB JSON (ISO requirements) are
authoritative; Qdrant is a rebuildable derived index. The collection name is
versioned (settings.qdrant_collection) — an embedding/chunker change means a
new collection, not an in-place mutation. ensure_collection() fails loudly if
an existing collection has the wrong dimension or distance.
"""

import uuid

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from app.config import settings
from app.services.embeddings import EMBEDDING_DIM

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.qdrant_url)
    return _client


def set_client(client: QdrantClient | None) -> None:
    """Test hook: inject QdrantClient(':memory:')."""
    global _client
    _client = client


def point_id(result_id: str) -> str:
    """Stable UUID5 for a result_id (chunk_id or kb:{version}:{req_id})."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, result_id))


def ensure_collection() -> None:
    client = get_client()
    name = settings.qdrant_collection
    if client.collection_exists(name):
        info = client.get_collection(name)
        params = info.config.params.vectors
        if params.size != EMBEDDING_DIM or params.distance != qm.Distance.COSINE:
            raise RuntimeError(
                f"Collection {name!r} incompatible (dim={params.size}, distance={params.distance}) — "
                f"attendu dim={EMBEDDING_DIM}, cosine. Changez de nom de collection et réindexez."
            )
        return
    client.create_collection(
        collection_name=name,
        vectors_config=qm.VectorParams(size=EMBEDDING_DIM, distance=qm.Distance.COSINE),
    )


def upsert_points(points: list[qm.PointStruct]) -> None:
    get_client().upsert(collection_name=settings.qdrant_collection, points=points, wait=True)


def delete_points_by_ids(ids: list[str]) -> None:
    if ids:
        get_client().delete(
            collection_name=settings.qdrant_collection,
            points_selector=qm.PointIdsList(points=ids),
            wait=True,
        )


def delete_points_by_document(document_id: str) -> None:
    client = get_client()
    if not client.collection_exists(settings.qdrant_collection):
        return  # nothing indexed yet -> nothing to delete
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(
                must=[qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))]
            )
        ),
        wait=True,
    )

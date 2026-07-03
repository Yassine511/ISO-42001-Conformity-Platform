"""Test fixtures: deterministic fake embedder + in-memory Qdrant (autouse).

Tests never download the embedding model and never need a Qdrant container.
The fake embedder is a hashed bag-of-words: texts sharing words get similar
vectors, which is enough signal for retrieval-ranking tests.
"""

import hashlib
import math

import pytest
from qdrant_client import QdrantClient

from app.services import embeddings, qdrant
from app.services.embeddings import EMBEDDING_DIM


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

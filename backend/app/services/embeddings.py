"""Embedding provider: fastembed MiniLM, lazily loaded, injectable for tests.

Model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384-dim,
natively supported by fastembed — NOT an e5 model, so no query/passage
prefixes). Tests replace the provider with a deterministic fake via
set_provider(); nothing here downloads the model until first real use.
"""

from typing import Protocol

from app.config import settings

EMBEDDING_DIM = 384


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastembedProvider:
    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(
            model_name=settings.embedding_model,
            cache_dir=settings.fastembed_cache_dir or None,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]


_provider: EmbeddingProvider | None = None


def set_provider(provider: EmbeddingProvider | None) -> None:
    global _provider
    _provider = provider


def embed_texts(texts: list[str]) -> list[list[float]]:
    global _provider
    if _provider is None:
        _provider = FastembedProvider()
    vectors = _provider.embed(texts)
    for v in vectors:
        if len(v) != EMBEDDING_DIM:
            raise RuntimeError(
                f"Vecteur de dimension {len(v)} (attendu {EMBEDDING_DIM}) — mauvais modèle d'embedding ?"
            )
    return vectors

"""Embedding backends for memory recall (spec §5.2).

FakeEmbedder is the default: deterministic hash-based unit vectors, so dev
and tests run with zero network. Identical texts get identical vectors and
distinct texts are near-orthogonal — supersession tests exploit this by
reusing the SAME text to force cosine 1.0. GeminiEmbedder calls
gemini-embedding-001 over REST; embedding_model is stored per memory doc,
so a future provider switch is a re-embed, not a redesign.
"""

import hashlib
import math
from abc import ABC, abstractmethod

import httpx

from switchgear.config import Settings

GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "gemini-embedding-001:batchEmbedContents")
_TASK_TYPES = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


class EmbeddingError(Exception):
    pass


class Embedder(ABC):
    model_name: str
    dim: int

    @abstractmethod
    async def embed(self, texts: list[str], *, task: str = "document") -> list[list[float]]:
        """task is "document" (at save) or "query" (at recall)."""


class FakeEmbedder(Embedder):
    model_name = "fake"
    dim = 64

    async def embed(self, texts: list[str], *, task: str = "document") -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        seed = hashlib.sha256(text.encode()).digest()
        raw: list[float] = []
        counter = 0
        while len(raw) < self.dim:
            block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            raw.extend(byte / 255.0 - 0.5 for byte in block)
            counter += 1
        vec = raw[: self.dim]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class GeminiEmbedder(Embedder):
    model_name = "gemini-embedding-001"
    dim = 768

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def embed(self, texts: list[str], *, task: str = "document") -> list[list[float]]:
        body = {"requests": [{
            "model": "models/gemini-embedding-001",
            "content": {"parts": [{"text": text}]},
            "taskType": _TASK_TYPES.get(task, "RETRIEVAL_DOCUMENT"),
            "outputDimensionality": self.dim,
        } for text in texts]}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(GEMINI_URL, json=body,
                                     headers={"x-goog-api-key": self._api_key})
        if resp.status_code >= 400:
            raise EmbeddingError(f"gemini embeddings error {resp.status_code}")
        try:
            out = [[float(v) for v in e["values"]] for e in resp.json()["embeddings"]]
        except (KeyError, TypeError, ValueError) as e:
            raise EmbeddingError(f"malformed embeddings response: {e}") from None
        if len(out) != len(texts):
            raise EmbeddingError(f"expected {len(texts)} embeddings, got {len(out)}")
        for vec in out:
            if len(vec) != self.dim:
                raise EmbeddingError(f"expected dim {self.dim}, got {len(vec)}")
        return out


def get_embedder(settings: Settings) -> Embedder:
    if settings.embedding_backend == "fake":
        return FakeEmbedder()
    if settings.embedding_backend == "gemini":
        return GeminiEmbedder(settings.gemini_api_key)
    raise ValueError(f"unknown embedding_backend: {settings.embedding_backend!r}")

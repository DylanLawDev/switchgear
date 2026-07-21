import json

import httpx
import pytest
import respx

from switchgear.config import Settings
from switchgear.memory.embeddings import (
    GEMINI_URL,
    Embedder,
    EmbeddingError,
    FakeEmbedder,
    GeminiEmbedder,
    get_embedder,
)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


# ---------- config defaults (spec §6, phase-2 subset — must be verbatim) ----------


def test_settings_memory_defaults():
    s = Settings(_env_file=None)
    assert s.embedding_backend == "fake"
    assert s.gemini_api_key == ""
    assert s.memory_max_chars == 1000
    assert s.memory_core_max_chars == 6000
    assert s.memory_recall_k == 4
    assert s.memory_recall_floor == 0.55
    assert s.memory_supersede_threshold == 0.92
    assert s.memory_recency_half_life_days == 14.0


# ---------- FakeEmbedder ----------


async def test_fake_is_deterministic_across_instances():
    a = (await FakeEmbedder().embed(["prefers tabs"]))[0]
    b = (await FakeEmbedder().embed(["prefers tabs"]))[0]
    assert a == b


async def test_fake_dim_and_unit_norm():
    vecs = await FakeEmbedder().embed(["one", "two"])
    for v in vecs:
        assert len(v) == 64
        assert dot(v, v) == pytest.approx(1.0)


async def test_fake_identical_texts_have_cosine_one():
    # Supersession tests rely on this: to force cosine 1.0 between two saves,
    # use the SAME text — distinct texts are near-orthogonal by construction.
    v1, v2 = await FakeEmbedder().embed(["use uv", "use uv"])
    assert dot(v1, v2) == pytest.approx(1.0)


async def test_fake_distinct_texts_near_orthogonal():
    texts = ["prefers tabs", "lives in Toronto", "commit in imperative mood"]
    vecs = await FakeEmbedder().embed(texts)
    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            # generous bound: expected |cos| ~ 1/sqrt(64) = 0.125; anything
            # below 0.5 stays far under the 0.55 floor and 0.92 threshold
            assert abs(dot(vecs[i], vecs[j])) < 0.5


async def test_fake_ignores_task_kind():
    emb = FakeEmbedder()
    doc = (await emb.embed(["hello"], task="document"))[0]
    query = (await emb.embed(["hello"], task="query"))[0]
    assert doc == query


def test_fake_metadata():
    emb = FakeEmbedder()
    assert emb.model_name == "fake"
    assert emb.dim == 64
    assert isinstance(emb, Embedder)


# ---------- factory ----------


def test_get_embedder_fake_default():
    assert isinstance(get_embedder(Settings(_env_file=None)), FakeEmbedder)


def test_get_embedder_gemini():
    s = Settings(_env_file=None, embedding_backend="gemini", gemini_api_key="k3y")
    emb = get_embedder(s)
    assert isinstance(emb, GeminiEmbedder)
    assert emb.model_name == "gemini-embedding-001"
    assert emb.dim == 768


def test_get_embedder_unknown_backend_raises():
    with pytest.raises(ValueError, match="embedding_backend"):
        get_embedder(Settings(_env_file=None, embedding_backend="cohere"))


# ---------- GeminiEmbedder (respx only — zero real network) ----------


def gemini_response(n=1):
    return httpx.Response(200, json={"embeddings": [{"values": [0.1] * 768}] * n})


@respx.mock
async def test_gemini_request_shape_document():
    route = respx.post(GEMINI_URL).mock(return_value=gemini_response(2))
    out = await GeminiEmbedder("k3y").embed(["alpha", "beta"])
    assert out == [[0.1] * 768, [0.1] * 768]
    req = route.calls[0].request
    assert req.headers["x-goog-api-key"] == "k3y"
    body = json.loads(req.content)
    assert len(body["requests"]) == 2
    first = body["requests"][0]
    assert first["model"] == "models/gemini-embedding-001"
    assert first["content"] == {"parts": [{"text": "alpha"}]}
    assert first["taskType"] == "RETRIEVAL_DOCUMENT"
    assert first["outputDimensionality"] == 768


@respx.mock
async def test_gemini_request_shape_query():
    route = respx.post(GEMINI_URL).mock(return_value=gemini_response())
    await GeminiEmbedder("k3y").embed(["what editor?"], task="query")
    body = json.loads(route.calls[0].request.content)
    assert body["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


@respx.mock
async def test_gemini_http_error_raises_embedding_error():
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(500, json={}))
    with pytest.raises(EmbeddingError):
        await GeminiEmbedder("k3y").embed(["x"])


@respx.mock
async def test_gemini_malformed_body_raises_embedding_error():
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json={"nope": []}))
    with pytest.raises(EmbeddingError):
        await GeminiEmbedder("k3y").embed(["x"])


@respx.mock
async def test_gemini_response_length_mismatch_raises_embedding_error():
    # 3 texts requested, only 2 embeddings returned — a short/reordered batch
    # response must not be silently zipped against the wrong texts.
    respx.post(GEMINI_URL).mock(return_value=gemini_response(2))
    with pytest.raises(EmbeddingError, match="expected 3 embeddings, got 2"):
        await GeminiEmbedder("k3y").embed(["a", "b", "c"])


@respx.mock
async def test_gemini_malformed_values_shape_raises_embedding_error():
    respx.post(GEMINI_URL).mock(
        return_value=httpx.Response(200, json={"embeddings": [{"values": "notalist"}]}))
    with pytest.raises(EmbeddingError):
        await GeminiEmbedder("k3y").embed(["x"])


@respx.mock
async def test_gemini_wrong_vector_dim_raises_embedding_error():
    # Right count of embeddings (1 for 1 text) but the vector itself is the
    # wrong length — recall's cosine() zip would silently truncate this.
    respx.post(GEMINI_URL).mock(
        return_value=httpx.Response(200, json={"embeddings": [{"values": [0.1] * 5}]}))
    with pytest.raises(EmbeddingError, match="expected dim 768, got 5"):
        await GeminiEmbedder("k3y").embed(["x"])

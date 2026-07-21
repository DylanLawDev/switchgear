import pytest

from switchgear.config import Settings
from switchgear.memory.embeddings import FakeEmbedder
from switchgear.memory.store import COLLECTION, MemoryError, MemoryStore, cosine
from switchgear.storage.memory import MemoryStorage


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class FailingEmbedder:
    """Embedder stub whose backend is down; save/recall must degrade, not raise."""

    model_name = "failing"
    dim = 64

    async def embed(self, texts, *, task="document"):
        raise RuntimeError("embedding backend down")


def make_store(embedder=None, clock=None, **overrides):
    storage = MemoryStorage()
    settings = Settings(_env_file=None, **overrides)
    clock = clock or Clock()
    store = MemoryStore(storage, embedder or FakeEmbedder(), settings, clock=clock)
    return store, storage, clock


# ---------- cosine ----------


def test_cosine_basics():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


# ---------- save: validation ----------


async def test_save_rejects_empty_and_whitespace_text():
    store, _, _ = make_store()
    with pytest.raises(MemoryError):
        await store.save("", type="episodic", importance=5)
    with pytest.raises(MemoryError):
        await store.save("   \n ", type="episodic", importance=5)


async def test_save_rejects_oversized_text():
    store, _, _ = make_store(memory_max_chars=10)
    with pytest.raises(MemoryError):
        await store.save("x" * 11, type="episodic", importance=5)


async def test_save_rejects_bad_type():
    store, _, _ = make_store()
    with pytest.raises(MemoryError):
        await store.save("hello", type="semantic", importance=5)


async def test_save_clamps_importance_instead_of_raising():
    store, _, _ = make_store()
    low = await store.save("low", type="episodic", importance=0)
    high = await store.save("high", type="episodic", importance=99)
    frac = await store.save("frac", type="episodic", importance=7.9)
    assert low["importance"] == 1
    assert high["importance"] == 10
    assert frac["importance"] == 7


# ---------- save: doc shape ----------


async def test_save_episodic_doc_shape():
    store, storage, clock = make_store()
    doc = await store.save("  Alex prefers tabs  ", type="episodic", importance=8,
                           conversation_id="c1")
    assert doc["key"].startswith("mem-") and len(doc["key"]) == 16
    assert doc["text"] == "Alex prefers tabs"  # stripped
    assert doc["type"] == "episodic"
    assert doc["status"] == "active"
    assert doc["importance"] == 8
    assert len(doc["embedding"]) == 64
    assert doc["embedding_model"] == "fake"
    assert doc["source"] == "owner"
    assert doc["conversation_id"] == "c1"
    assert doc["superseded_by"] is None
    assert doc["created_at"] == clock.now
    assert doc["updated_at"] == clock.now
    assert doc["last_accessed_at"] is None
    assert doc["access_count"] == 0
    stored = await storage.get(COLLECTION, doc["key"])
    assert stored["embedding"] == doc["embedding"]


async def test_save_core_has_no_embedding():
    store, _, _ = make_store()
    doc = await store.save("Always commit in imperative mood", type="core", importance=9)
    assert doc["embedding"] is None
    assert doc["embedding_model"] is None


# ---------- save: supersession ----------


async def test_episodic_supersession_on_identical_text():
    # FakeEmbedder gives identical texts cosine 1.0 >= the 0.92 threshold;
    # distinct texts are near-orthogonal. Same text = the supersession trick.
    store, storage, clock = make_store()
    old = await store.save("prefers tabs", type="episodic", importance=5)
    clock.now += 60
    new = await store.save("prefers tabs", type="episodic", importance=5)
    old_stored = await storage.get(COLLECTION, old["key"])
    assert old_stored["status"] == "superseded"
    assert old_stored["superseded_by"] == new["key"]
    assert old_stored["updated_at"] == clock.now
    assert "_id" not in old_stored  # query() artifact must not be persisted
    assert (await storage.get(COLLECTION, new["key"]))["status"] == "active"


async def test_episodic_distinct_texts_do_not_supersede():
    store, storage, _ = make_store()
    a = await store.save("prefers tabs", type="episodic", importance=5)
    await store.save("lives in Toronto", type="episodic", importance=5)
    assert (await storage.get(COLLECTION, a["key"]))["status"] == "active"


async def test_supersession_only_scans_active_docs():
    store, storage, _ = make_store()
    first = await store.save("prefers tabs", type="episodic", importance=5)
    second = await store.save("prefers tabs", type="episodic", importance=5)
    third = await store.save("prefers tabs", type="episodic", importance=5)
    assert (await storage.get(COLLECTION, first["key"]))["superseded_by"] == second["key"]
    assert (await storage.get(COLLECTION, second["key"]))["superseded_by"] == third["key"]


async def test_core_supersedes_on_normalized_exact_text():
    store, storage, _ = make_store()
    old = await store.save("Use  UV   for Python", type="core", importance=5)
    new = await store.save("use uv for python", type="core", importance=5)
    old_stored = await storage.get(COLLECTION, old["key"])
    assert old_stored["status"] == "superseded"
    assert old_stored["superseded_by"] == new["key"]


async def test_core_different_text_does_not_supersede():
    store, storage, _ = make_store()
    a = await store.save("use uv", type="core", importance=5)
    await store.save("use ruff", type="core", importance=5)
    assert (await storage.get(COLLECTION, a["key"]))["status"] == "active"


async def test_no_cross_type_supersession():
    store, storage, _ = make_store()
    core = await store.save("prefers tabs", type="core", importance=5)
    episodic = await store.save("prefers tabs", type="episodic", importance=5)
    assert (await storage.get(COLLECTION, core["key"]))["status"] == "active"
    assert (await storage.get(COLLECTION, episodic["key"]))["status"] == "active"


# ---------- save: degradation + audit ----------


async def test_embedding_failure_at_save_stores_null_and_does_not_raise():
    store, storage, _ = make_store(embedder=FailingEmbedder())
    doc = await store.save("prefers tabs", type="episodic", importance=5)
    stored = await storage.get(COLLECTION, doc["key"])
    assert stored["status"] == "active"
    assert stored["embedding"] is None
    assert stored["embedding_model"] is None


async def test_save_audits():
    store, storage, _ = make_store()
    doc = await store.save("prefers tabs", type="episodic", importance=5,
                           source="reflection")
    audit = await storage.query("audit")
    assert len(audit) == 1
    assert audit[0]["action"] == "memory_save"
    assert audit[0]["key"] == doc["key"]
    assert audit[0]["source"] == "reflection"
    assert isinstance(audit[0]["at"], float)


# ---------- recall ----------


class VectorEmbedder:
    """Preset vectors per text: lets recall tests control cosine exactly.
    The query text maps to its own vector too."""

    model_name = "stub"
    dim = 4

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors

    async def embed(self, texts, *, task="document"):
        return [list(self.vectors[t]) for t in texts]


QUERY = [1.0, 0.0, 0.0, 0.0]


def vector_store(vectors, clock=None, **overrides):
    # pin the supersede threshold above any achievable cosine so multi-doc
    # recall fixtures survive save()'s supersession pass
    overrides.setdefault("memory_supersede_threshold", 1.01)
    return make_store(embedder=VectorEmbedder(vectors), clock=clock, **overrides)


async def test_recall_orders_by_cosine_and_filters_floor():
    store, _, _ = vector_store({
        "q": QUERY,
        "exact": [1.0, 0.0, 0.0, 0.0],
        "close": [0.8, 0.6, 0.0, 0.0],
        "far": [0.0, 1.0, 0.0, 0.0],
    })
    await store.save("far", type="episodic", importance=5)
    await store.save("close", type="episodic", importance=5)
    await store.save("exact", type="episodic", importance=5)
    out = await store.recall("q")
    assert [d["text"] for d in out] == ["exact", "close"]  # "far" is under the 0.55 floor
    assert all("embedding" not in d for d in out)


async def test_recall_floor_yields_empty_list_first_class():
    store, _, _ = vector_store({"q": QUERY, "far": [0.0, 1.0, 0.0, 0.0]})
    await store.save("far", type="episodic", importance=10)
    assert await store.recall("q") == []


async def test_recall_floor_zero_is_a_real_override_not_falsy_default():
    store, _, _ = vector_store({"q": QUERY, "far": [0.0, 1.0, 0.0, 0.0]})
    await store.save("far", type="episodic", importance=5)
    assert [d["text"] for d in await store.recall("q", floor=0.0)] == ["far"]


async def test_recall_importance_lifts_lower_cosine_doc():
    store, _, _ = vector_store({
        "q": QUERY,
        "meh-but-critical": [0.95, 0.312, 0.0, 0.0],
        "exact-but-trivial": [1.0, 0.0, 0.0, 0.0],
    })
    await store.save("exact-but-trivial", type="episodic", importance=1)
    await store.save("meh-but-critical", type="episodic", importance=10)
    out = await store.recall("q")
    # 0.70*0.95 + 0.15*1.0 (importance) beats 0.70*1.0 + 0.15*0.1
    assert [d["text"] for d in out] == ["meh-but-critical", "exact-but-trivial"]


async def test_recall_recency_decay_prefers_fresh_docs():
    clock = Clock()
    sym = 0.19 ** 0.5  # [0.9, ±sym] are unit vectors with cosine 0.9 to QUERY
    store, _, _ = vector_store({
        "q": QUERY,
        "old": [0.9, sym, 0.0, 0.0],
        "new": [0.9, -sym, 0.0, 0.0],
    }, clock=clock)
    await store.save("old", type="episodic", importance=5)
    clock.now += 28 * 86400  # two half-lives: recency 1.0 -> 0.25
    await store.save("new", type="episodic", importance=5)
    out = await store.recall("q")
    assert [d["text"] for d in out] == ["new", "old"]


async def test_recall_k_limits_results_and_defaults_from_settings():
    vectors = {"q": QUERY}
    for i in range(6):
        vectors[f"m{i}"] = QUERY  # six distinct texts, all cosine 1.0 to the query
    store, _, _ = vector_store(vectors)
    for i in range(6):
        await store.save(f"m{i}", type="episodic", importance=5)
    assert len(await store.recall("q")) == 4  # memory_recall_k default
    assert len(await store.recall("q", k=2)) == 2


async def test_recall_touches_access_metadata():
    clock = Clock()
    store, storage, _ = vector_store({"q": QUERY, "hit": QUERY,
                                      "miss": [0.0, 1.0, 0.0, 0.0]}, clock=clock)
    hit = await store.save("hit", type="episodic", importance=5)
    miss = await store.save("miss", type="episodic", importance=5)
    clock.now += 100
    await store.recall("q")
    hit_doc = await storage.get(COLLECTION, hit["key"])
    assert hit_doc["last_accessed_at"] == clock.now
    assert hit_doc["access_count"] == 1
    miss_doc = await storage.get(COLLECTION, miss["key"])
    assert miss_doc["last_accessed_at"] is None
    assert miss_doc["access_count"] == 0


async def test_recall_ignores_superseded_docs():
    store, _, _ = make_store()  # real FakeEmbedder; identical text supersedes
    await store.save("prefers tabs", type="episodic", importance=5)
    kept = await store.save("prefers tabs", type="episodic", importance=5)
    out = await store.recall("prefers tabs")
    assert [d["key"] for d in out] == [kept["key"]]


# ---------- recall: degradation + backfill ----------


class DocumentsDownEmbedder(FakeEmbedder):
    """Query embeds work; document embeds fail — exercises backfill failure."""

    async def embed(self, texts, *, task="document"):
        if task == "document":
            raise RuntimeError("document embeds down")
        return await super().embed(texts, task=task)


class FlakyEmbedder(FakeEmbedder):
    """Fails the first N embed calls, then recovers."""

    def __init__(self, failures: int):
        self.failures = failures

    async def embed(self, texts, *, task="document"):
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("temporary outage")
        return await super().embed(texts, task=task)


async def test_embedder_failure_at_recall_returns_empty():
    store, _, _ = make_store(embedder=FailingEmbedder())
    assert await store.recall("anything") == []


async def test_recall_backfills_null_embeddings_and_persists():
    store, storage, _ = make_store(embedder=FlakyEmbedder(failures=1))
    doc = await store.save("prefers tabs", type="episodic", importance=5)
    assert (await storage.get(COLLECTION, doc["key"]))["embedding"] is None
    out = await store.recall("prefers tabs")  # query embed + backfill both succeed
    assert [d["key"] for d in out] == [doc["key"]]
    repaired = await storage.get(COLLECTION, doc["key"])
    assert repaired["embedding"] is not None
    assert repaired["embedding_model"] == "fake"


async def test_recall_skips_docs_that_still_fail_backfill():
    store, storage, _ = make_store(embedder=DocumentsDownEmbedder())
    doc = await store.save("prefers tabs", type="episodic", importance=5)
    assert await store.recall("prefers tabs") == []
    assert (await storage.get(COLLECTION, doc["key"]))["embedding"] is None


# ---------- core_block ----------


async def test_core_block_empty_corpus_is_empty_string():
    store, _, _ = make_store()
    assert await store.core_block() == ""


async def test_core_block_newest_first_bullets():
    clock = Clock()
    store, _, _ = make_store(clock=clock)
    await store.save("older rule", type="core", importance=5)
    clock.now += 60
    await store.save("newer rule", type="core", importance=5)
    assert await store.core_block() == "- newer rule\n- older rule"


async def test_core_block_ignores_episodic_docs():
    store, _, _ = make_store()
    await store.save("core rule", type="core", importance=5)
    await store.save("episodic fact", type="episodic", importance=5)
    assert await store.core_block() == "- core rule"


async def test_core_block_truncates_oldest_with_omission_note():
    clock = Clock()
    store, _, _ = make_store(clock=clock, memory_core_max_chars=80)
    for i in range(5):
        await store.save(f"standing rule number {i}", type="core", importance=5)
        clock.now += 60
    block = await store.core_block()
    assert block == ("- standing rule number 4\n"
                     "(older standing instructions omitted — see /memories)")


# ---------- list / update / archive / restore / delete ----------


async def test_list_sorted_newest_first_and_strips_embedding():
    clock = Clock()
    store, _, _ = make_store(clock=clock)
    await store.save("first", type="episodic", importance=5)
    clock.now += 60
    await store.save("second", type="core", importance=5)
    rows = await store.list()
    assert [r["text"] for r in rows] == ["second", "first"]
    assert all("embedding" not in r and "_id" not in r for r in rows)


async def test_list_filters_by_status_and_type():
    store, _, _ = make_store()
    a = await store.save("core rule", type="core", importance=5)
    b = await store.save("a fact", type="episodic", importance=5)
    await store.archive(b["key"])
    assert [r["key"] for r in await store.list(type="core")] == [a["key"]]
    assert [r["key"] for r in await store.list(status="archived")] == [b["key"]]
    assert await store.list(status="active", type="episodic") == []


async def test_update_text_reembeds_episodic():
    store, storage, _ = make_store()
    doc = await store.save("prefers tabs", type="episodic", importance=5)
    before = (await storage.get(COLLECTION, doc["key"]))["embedding"]
    out = await store.update_text(doc["key"], "prefers spaces")
    assert out["text"] == "prefers spaces"
    assert "embedding" not in out
    after = (await storage.get(COLLECTION, doc["key"]))["embedding"]
    assert after != before  # deterministic fake: new text, new vector


async def test_update_text_core_keeps_null_embedding():
    store, storage, _ = make_store()
    doc = await store.save("old rule", type="core", importance=5)
    await store.update_text(doc["key"], "new rule")
    assert (await storage.get(COLLECTION, doc["key"]))["embedding"] is None


async def test_update_text_missing_returns_none_and_validates():
    store, _, _ = make_store()
    assert await store.update_text("mem-none", "x") is None
    doc = await store.save("valid", type="episodic", importance=5)
    with pytest.raises(MemoryError):
        await store.update_text(doc["key"], "   ")


async def test_update_text_embedding_failure_degrades_to_null():
    store, storage, _ = make_store(embedder=FlakyEmbedder(failures=0))
    doc = await store.save("prefers tabs", type="episodic", importance=5)
    store._embedder.failures = 1  # next embed call fails
    out = await store.update_text(doc["key"], "prefers spaces")
    assert out["text"] == "prefers spaces"
    assert (await storage.get(COLLECTION, doc["key"]))["embedding"] is None


async def test_update_text_episodic_supersedes_other_active_doc_with_matching_text():
    # Editing A to B's text should supersede B, mirroring save-time semantics
    # where the newest text wins. FakeEmbedder gives identical texts cosine 1.0.
    store, storage, clock = make_store()
    a = await store.save("prefers tabs", type="episodic", importance=5)
    b = await store.save("lives in Toronto", type="episodic", importance=5)
    clock.now += 60
    out = await store.update_text(a["key"], "lives in Toronto")
    assert out["text"] == "lives in Toronto"
    b_stored = await storage.get(COLLECTION, b["key"])
    assert b_stored["status"] == "superseded"
    assert b_stored["superseded_by"] == a["key"]
    assert b_stored["updated_at"] == clock.now
    a_stored = await storage.get(COLLECTION, a["key"])
    assert a_stored["status"] == "active"


async def test_update_text_core_supersedes_other_active_doc_with_matching_normalized_text():
    store, storage, clock = make_store()
    a = await store.save("use uv", type="core", importance=5)
    b = await store.save("use ruff", type="core", importance=5)
    clock.now += 60
    await store.update_text(a["key"], "Use  Ruff ")
    b_stored = await storage.get(COLLECTION, b["key"])
    assert b_stored["status"] == "superseded"
    assert b_stored["superseded_by"] == a["key"]


async def test_update_text_does_not_supersede_self():
    store, storage, _ = make_store()
    doc = await store.save("prefers tabs", type="episodic", importance=5)
    await store.update_text(doc["key"], "prefers tabs")
    stored = await storage.get(COLLECTION, doc["key"])
    assert stored["status"] == "active"
    assert stored["superseded_by"] is None


async def test_update_text_refuses_archived_doc():
    store, storage, _ = make_store()
    doc = await store.save("prefers tabs", type="episodic", importance=5)
    await store.archive(doc["key"])
    audits_before = len(await storage.query("audit"))
    assert await store.update_text(doc["key"], "prefers spaces") is None
    stored = await storage.get(COLLECTION, doc["key"])
    assert stored["text"] == "prefers tabs"
    assert stored["status"] == "archived"
    assert len(await storage.query("audit")) == audits_before


async def test_update_text_refuses_superseded_doc():
    store, storage, _ = make_store()
    old = await store.save("prefers tabs", type="episodic", importance=5)
    await store.save("prefers tabs", type="episodic", importance=5)  # supersedes old
    audits_before = len(await storage.query("audit"))
    assert await store.update_text(old["key"], "something else") is None
    stored = await storage.get(COLLECTION, old["key"])
    assert stored["text"] == "prefers tabs"
    assert stored["status"] == "superseded"
    assert len(await storage.query("audit")) == audits_before


async def test_archive_excludes_from_recall_and_core_block_until_restored():
    store, _, _ = make_store()
    core = await store.save("standing rule", type="core", importance=5)
    epi = await store.save("prefers tabs", type="episodic", importance=5)
    await store.archive(core["key"])
    await store.archive(epi["key"])
    assert await store.core_block() == ""
    assert await store.recall("prefers tabs") == []
    await store.restore(core["key"])
    await store.restore(epi["key"])
    assert await store.core_block() == "- standing rule"
    assert [d["key"] for d in await store.recall("prefers tabs")] == [epi["key"]]


async def test_archive_restore_missing_returns_none():
    store, _, _ = make_store()
    assert await store.archive("mem-none") is None
    assert await store.restore("mem-none") is None


async def test_restore_refuses_superseded_docs():
    # restore is the inverse of archive only (spec §5.3): a superseded doc must
    # stay superseded, or restoring it would recreate the duplicate-active
    # situation supersession exists to prevent.
    store, storage, _ = make_store()
    old = await store.save("prefers tabs", type="episodic", importance=5)
    new = await store.save("prefers tabs", type="episodic", importance=5)
    audits_before = len(await storage.query("audit"))
    assert await store.restore(old["key"]) is None
    stored = await storage.get(COLLECTION, old["key"])
    assert stored["status"] == "superseded"
    assert stored["superseded_by"] == new["key"]
    assert len(await storage.query("audit")) == audits_before  # no memory_restore audit


async def test_archive_refuses_superseded_docs():
    # archive is active-only (Task 4 reviewer follow-up): archiving a
    # superseded doc then restoring it would resurrect a duplicate-active
    # memory, escaping the restore guard via two calls instead of one.
    store, storage, _ = make_store()
    old = await store.save("prefers tabs", type="episodic", importance=5)
    new = await store.save("prefers tabs", type="episodic", importance=5)
    audits_before = len(await storage.query("audit"))
    assert await store.archive(old["key"]) is None
    stored = await storage.get(COLLECTION, old["key"])
    assert stored["status"] == "superseded"
    assert stored["superseded_by"] == new["key"]
    assert len(await storage.query("audit")) == audits_before  # no memory_archive audit


async def test_restore_refuses_when_active_duplicate_exists():
    # archive A (core "X"), then save A' ("X") active — save-time supersession
    # only scans ACTIVE docs, so it never sees archived A. Restoring A must
    # not create a second active "X", or the supersession invariant breaks.
    store, storage, _ = make_store()
    a = await store.save("X", type="core", importance=5)
    await store.archive(a["key"])
    a_prime = await store.save("X", type="core", importance=5)
    audits_before = len(await storage.query("audit"))
    assert await store.restore(a["key"]) is None
    stored = await storage.get(COLLECTION, a["key"])
    assert stored["status"] == "archived"
    assert (await storage.get(COLLECTION, a_prime["key"]))["status"] == "active"
    assert len(await storage.query("audit")) == audits_before  # no memory_restore audit


async def test_restore_refuses_when_active_episodic_duplicate_exists():
    store, storage, _ = make_store()  # FakeEmbedder: identical text -> cosine 1.0
    a = await store.save("prefers tabs", type="episodic", importance=5)
    await store.archive(a["key"])
    a_prime = await store.save("prefers tabs", type="episodic", importance=5)
    assert await store.restore(a["key"]) is None
    stored = await storage.get(COLLECTION, a["key"])
    assert stored["status"] == "archived"
    assert (await storage.get(COLLECTION, a_prime["key"]))["status"] == "active"


async def test_restore_succeeds_when_no_active_duplicate_exists():
    store, storage, _ = make_store()
    a = await store.save("X", type="core", importance=5)
    await store.archive(a["key"])
    out = await store.restore(a["key"])
    assert out is not None
    assert out["status"] == "active"
    assert (await storage.get(COLLECTION, a["key"]))["status"] == "active"


async def test_archive_refuses_already_archived_docs():
    store, storage, _ = make_store()
    doc = await store.save("active fact", type="episodic", importance=5)
    await store.archive(doc["key"])
    audits_before = len(await storage.query("audit"))
    assert await store.archive(doc["key"]) is None
    assert (await storage.get(COLLECTION, doc["key"]))["status"] == "archived"
    assert len(await storage.query("audit")) == audits_before


async def test_restore_refuses_already_active_docs():
    store, storage, _ = make_store()
    doc = await store.save("active fact", type="episodic", importance=5)
    audits_before = len(await storage.query("audit"))
    assert await store.restore(doc["key"]) is None
    assert (await storage.get(COLLECTION, doc["key"]))["status"] == "active"
    assert len(await storage.query("audit")) == audits_before


async def test_delete_removes_doc_and_returns_flags():
    store, storage, _ = make_store()
    doc = await store.save("gone soon", type="episodic", importance=5)
    assert await store.delete(doc["key"]) is True
    assert await storage.get(COLLECTION, doc["key"]) is None
    assert await store.delete(doc["key"]) is False


async def test_lifecycle_writes_all_audit():
    store, storage, _ = make_store()
    doc = await store.save("audited", type="episodic", importance=5)
    await store.update_text(doc["key"], "audited edit")
    await store.archive(doc["key"])
    await store.restore(doc["key"])
    await store.delete(doc["key"])
    records = await storage.query("audit")
    assert sorted(a["action"] for a in records) == [
        "memory_archive", "memory_delete", "memory_restore",
        "memory_save", "memory_update_text"]
    assert all(a["key"] == doc["key"] for a in records)

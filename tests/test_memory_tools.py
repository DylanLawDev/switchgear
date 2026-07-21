import json

from switchgear.config import Settings
from switchgear.memory.embeddings import FakeEmbedder
from switchgear.memory.store import MemoryStore
from switchgear.storage.memory import MemoryStorage
from switchgear.tools import build_registry
from switchgear.tools.memory_tools import make_save_memory_tool, make_search_memory_tool
from tests.fakes import FakeGateway


def make_store():
    return MemoryStore(MemoryStorage(), FakeEmbedder(), Settings(_env_file=None))


# ---------- schemas ----------


def test_save_memory_schema_and_write_policy():
    tool = make_save_memory_tool(make_store())
    assert tool.name == "save_memory"
    assert set(tool.parameters["required"]) == {"text", "type", "importance"}
    assert tool.parameters["properties"]["type"]["enum"] == ["core", "episodic"]
    desc = tool.description.lower()
    # the owner-utterance-only write policy must ride in the description
    for phrase in ("owner", "never", "tool results", "fetched pages", "emails",
                   "transient"):
        assert phrase in desc


def test_search_memory_schema():
    tool = make_search_memory_tool(make_store())
    assert tool.name == "search_memory"
    assert tool.parameters["required"] == ["query"]
    assert "k" in tool.parameters["properties"]


# ---------- save handler ----------


async def test_save_memory_returns_ok_and_key():
    store = make_store()
    tool = make_save_memory_tool(store)
    out = json.loads(await tool.handler(text="prefers tabs", type="episodic",
                                        importance=7))
    assert out["ok"] is True
    assert out["key"].startswith("mem-")
    saved = await store.list()
    assert saved[0]["text"] == "prefers tabs"
    assert saved[0]["source"] == "owner"


async def test_save_memory_validation_error_returns_error_dict():
    tool = make_save_memory_tool(make_store())
    out = json.loads(await tool.handler(text="", type="episodic", importance=5))
    assert "error" in out
    out = json.loads(await tool.handler(text="x", type="semantic", importance=5))
    assert "error" in out


# ---------- search handler ----------


async def test_search_memory_returns_projection_without_embeddings():
    store = make_store()
    await store.save("prefers tabs", type="episodic", importance=7)
    tool = make_search_memory_tool(store)
    out = json.loads(await tool.handler(query="prefers tabs"))
    assert len(out) == 1
    assert set(out[0]) == {"key", "text", "type", "importance", "created_at"}


async def test_search_memory_empty_result_is_normal():
    tool = make_search_memory_tool(make_store())
    assert json.loads(await tool.handler(query="anything")) == []


class RecordingStore:
    def __init__(self):
        self.calls = []

    async def recall(self, query, k=None, floor=None):
        self.calls.append((query, k, floor))
        return []


async def test_search_memory_caps_k_at_ten_and_defaults_to_four():
    rec = RecordingStore()
    tool = make_search_memory_tool(rec)
    await tool.handler(query="x", k=99)
    await tool.handler(query="x")
    assert rec.calls[0] == ("x", 10, None)
    assert rec.calls[1] == ("x", 4, None)


# ---------- registry wiring ----------


def test_build_registry_registers_memory_tools_when_store_present():
    settings = Settings(_env_file=None)
    storage = MemoryStorage()
    store = MemoryStore(storage, FakeEmbedder(), settings)
    reg = build_registry(settings, storage, FakeGateway([]), memory_store=store)
    assert "save_memory" in reg._tools
    assert "search_memory" in reg._tools


def test_build_registry_omits_memory_tools_without_store():
    reg = build_registry(Settings(_env_file=None), MemoryStorage(), FakeGateway([]))
    assert "save_memory" not in reg._tools
    assert "search_memory" not in reg._tools

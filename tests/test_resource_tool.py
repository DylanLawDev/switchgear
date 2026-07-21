import json

from switchgear.config import Settings
from switchgear.resources.agent_writes import AgentWriteService
from switchgear.resources.store import ResourceStore
from switchgear.storage.memory import MemoryStorage
from switchgear.tools.base import ToolRegistry
from switchgear.tools.resource_tool import make_resources_tool

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")


def setup(settings=S, writes=False):
    storage = MemoryStorage()
    store = ResourceStore(storage, settings)
    reg = ToolRegistry()
    service = AgentWriteService(store, storage) if writes else None
    reg.register(make_resources_tool(store, settings, writes=service))
    return reg, store


async def call(reg, **args):
    return json.loads(await reg.execute("resources", args))


async def test_list_shape():
    reg, store = setup()
    await store.save("career-bank", "json", "Resume facts bank", '{"a": 1}')
    await store.save("notes", "md", "team notes", "# hi")
    out = await call(reg, op="list")
    assert out == [
        {"name": "career-bank", "kind": "json", "description": "Resume facts bank",
         "size": 8},
        {"name": "notes", "kind": "md", "description": "team notes", "size": 4},
    ]


async def test_read_shape():
    reg, store = setup()
    await store.save("notes", "md", "", "0123456789")
    out = await call(reg, op="read", name="notes")
    assert out == {"content": "0123456789", "size": 10, "kind": "md",
                   "offset": 0, "total_chars": 10}


async def test_read_window_offset_and_limit():
    reg, store = setup()
    await store.save("notes", "md", "", "0123456789")
    out = await call(reg, op="read", name="notes", offset=3, limit=4)
    assert out["content"] == "3456"
    assert out["offset"] == 3
    assert out["total_chars"] == 10


async def test_read_window_capped_at_resource_read_chars():
    small = Settings(_env_file=None, owner_email="me@example.com",
                     session_secret="s3", resource_read_chars=5)
    reg, store = setup(settings=small)
    await store.save("notes", "md", "", "0123456789")
    out = await call(reg, op="read", name="notes")
    assert out["content"] == "01234"          # default window capped
    out = await call(reg, op="read", name="notes", limit=9)
    assert out["content"] == "01234"          # explicit limit capped too
    out = await call(reg, op="read", name="notes", offset=8)
    assert out["content"] == "89"


async def test_read_negative_offset_clamps_to_zero():
    reg, store = setup()
    await store.save("notes", "md", "", "0123456789")
    out = await call(reg, op="read", name="notes", offset=-5)
    assert out["content"] == "0123456789"
    assert out["offset"] == 0
    assert out["total_chars"] == 10


async def test_read_offset_past_total_chars_is_empty():
    reg, store = setup()
    await store.save("notes", "md", "", "0123456789")
    out = await call(reg, op="read", name="notes", offset=100)
    assert out["content"] == ""
    assert out["offset"] == 100
    assert out["total_chars"] == 10


async def test_read_negative_limit_is_empty():
    reg, store = setup()
    await store.save("notes", "md", "", "0123456789")
    out = await call(reg, op="read", name="notes", limit=-1)
    assert out["content"] == ""
    assert out["offset"] == 0
    assert out["total_chars"] == 10


async def test_read_unknown_name_errors():
    reg, _ = setup()
    out = await call(reg, op="read", name="nope")
    assert "error" in out


async def test_unknown_op_errors():
    reg, _ = setup()
    out = await call(reg, op="write")
    assert "error" in out


async def test_write_ops_without_service_error():
    reg, _ = setup()
    out = await call(reg, op="create", name="n", kind="md", content="x")
    assert "error" in out


async def test_create_queues_in_prompt_mode():
    reg, store = setup(writes=True)
    out = await call(reg, op="create", name="notes", kind="md",
                     description="d", content="# hi")
    assert out["queued"] is True and out["applied"] is False
    assert await store.get("notes") is None


async def test_write_errors_returned_not_raised():
    reg, _ = setup(writes=True)
    out = await call(reg, op="update", name="ghost", content="x")
    assert "not found" in out["error"]


async def test_description_explains_write_modes():
    reg, _ = setup()
    desc = reg.get("resources").description
    assert "queued" in desc
    assert "ground truth" in desc


def make_registry(**kw):
    from tests.fakes import FakeGateway

    from switchgear.tools import build_registry

    return build_registry(S, MemoryStorage(), FakeGateway([]), **kw)


async def test_build_registry_registers_resources_only_with_store():
    without = make_registry()
    assert "resources" not in without._tools
    assert "career_bank" not in without._tools
    with_store = make_registry(resource_store=ResourceStore(MemoryStorage(), S))
    assert "resources" in with_store._tools
    assert "spawn_subagent" in with_store._tools

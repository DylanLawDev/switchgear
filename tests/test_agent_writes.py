import pytest

from switchgear.config import Settings
from switchgear.resources.agent_writes import AgentWriteService
from switchgear.resources.store import ResourceError, ResourceStore
from switchgear.storage.memory import MemoryStorage

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")


def make():
    storage = MemoryStorage()
    store = ResourceStore(storage, S)
    return storage, store, AgentWriteService(store, storage)


async def test_default_mode_is_prompt():
    _, _, svc = make()
    assert await svc.get_mode() == "prompt"


async def test_set_mode_validates():
    _, _, svc = make()
    assert await svc.set_mode("full") == "full"
    with pytest.raises(ResourceError):
        await svc.set_mode("yolo")


async def test_read_only_refuses_writes():
    _, _, svc = make()
    await svc.set_mode("read-only")
    with pytest.raises(ResourceError, match="read-only"):
        await svc.propose("create", "notes", kind="md", content="# hi")


async def test_prompt_mode_queues_and_approve_applies():
    _, store, svc = make()
    r = await svc.propose("create", "notes", kind="md",
                          description="d", content="# hi")
    assert r["applied"] is False and r["queued"] is True
    assert await store.get("notes") is None
    [p] = await svc.list_pending()
    assert p["resource_name"] == "notes" and p["op"] == "create"
    assert p["old_content"] is None and p["new_content"] == "# hi"
    assert isinstance(p["created_at"], str) and "T" in p["created_at"]
    assert await svc.approve(p["id"]) is True
    doc = await store.get("notes")
    assert doc["content"] == "# hi" and doc["source"] == "agent"
    assert await svc.list_pending() == []


async def test_full_mode_applies_immediately():
    _, store, svc = make()
    await svc.set_mode("full")
    r = await svc.propose("create", "notes", kind="md", content="# hi")
    assert r["applied"] is True
    assert (await store.get("notes"))["source"] == "agent"


async def test_op_state_rules():
    _, store, svc = make()
    await svc.set_mode("full")
    with pytest.raises(ResourceError, match="not found"):
        await svc.propose("update", "ghost", content="x")
    with pytest.raises(ResourceError, match="not found"):
        await svc.propose("delete", "ghost")
    await svc.propose("create", "notes", kind="md", content="a")
    with pytest.raises(ResourceError, match="already exists"):
        await svc.propose("create", "notes", kind="md", content="b")
    # update inherits stored kind/description when omitted
    await svc.propose("update", "notes", content="c")
    assert (await store.get("notes"))["content"] == "c"
    await svc.propose("delete", "notes")
    assert await store.get("notes") is None


async def test_invalid_content_fails_at_propose_even_in_prompt_mode():
    _, _, svc = make()
    with pytest.raises(ResourceError, match="not valid json"):
        await svc.propose("create", "data", kind="json", content="nope")
    assert await svc.list_pending() == []


async def test_reject_and_reject_for_resource():
    _, store, svc = make()
    await svc.propose("create", "notes", kind="md", content="a")
    [p] = await svc.list_pending()
    assert await svc.reject(p["id"]) is True
    assert await svc.list_pending() == []
    assert await store.get("notes") is None
    await svc.propose("create", "notes", kind="md", content="a")
    await svc.propose("create", "other", kind="md", content="b")
    assert await svc.reject_for_resource("notes") == 1
    assert [q["resource_name"] for q in await svc.list_pending()] == ["other"]


async def test_approve_stale_snapshot_is_refused():
    _, store, svc = make()
    await store.save("notes", "md", "", "v1")
    await svc.propose("update", "notes", content="v2")
    [p] = await svc.list_pending()
    await store.save("notes", "md", "", "v1-owner-edit")  # changed underneath
    with pytest.raises(ResourceError, match="changed"):
        await svc.approve(p["id"])


async def test_approve_unknown_returns_false():
    _, _, svc = make()
    assert await svc.approve("nope") is False
    assert await svc.reject("nope") is False


async def test_full_mode_create_race_is_refused(monkeypatch):
    # Simulate the resource being created between propose()'s initial
    # existence check and _apply()'s save() call.
    _, store, svc = make()
    await svc.set_mode("full")

    calls = {"n": 0}
    real_get = store.get

    async def racy_get(name):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # propose()'s initial check: nothing exists yet
        return {"kind": "md", "description": "", "content": "raced-in",
                "source": "human"}  # _apply()'s re-check: it appeared

    monkeypatch.setattr(store, "get", racy_get)
    with pytest.raises(ResourceError, match="already exists"):
        await svc.propose("create", "notes", kind="md", content="# hi")
    monkeypatch.setattr(store, "get", real_get)

    # The real store was never touched by save() — content wasn't overwritten.
    assert await store.get("notes") is None


async def test_read_only_refuses_before_content_validation():
    _, _, svc = make()
    await svc.set_mode("read-only")
    with pytest.raises(ResourceError, match="read-only") as exc_info:
        await svc.propose("create", "data", kind="json", content="not json")
    assert "not valid json" not in str(exc_info.value)


async def test_refusals_are_audited():
    storage, store, svc = make()
    await svc.set_mode("read-only")
    with pytest.raises(ResourceError, match="read-only"):
        await svc.propose("create", "notes", kind="md", content="# hi")
    audit_docs = await storage.query("audit")
    refusals = [d for d in audit_docs if d["action"] == "resource_agent_refused"]
    assert len(refusals) == 1
    assert refusals[0]["name"] == "notes"
    assert "read-only" in refusals[0]["detail"]

    # approve()'s staleness refusal is audited too.
    await svc.set_mode("prompt")
    await store.save("notes", "md", "", "v1")
    await svc.propose("update", "notes", content="v2")
    [p] = await svc.list_pending()
    await store.save("notes", "md", "", "v1-owner-edit")
    with pytest.raises(ResourceError, match="changed"):
        await svc.approve(p["id"])
    audit_docs = await storage.query("audit")
    refusals = [d for d in audit_docs if d["action"] == "resource_agent_refused"]
    assert len(refusals) == 2
    assert refusals[1]["name"] == "notes"
    assert "changed" in refusals[1]["detail"]

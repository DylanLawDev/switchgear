import json

from switchgear.skills.store import SkillStore
from switchgear.skills.agent_writes import SkillWriteService
from switchgear.storage.memory import MemoryStorage
from switchgear.tools.base import ToolRegistry
from switchgear.tools.skill_tools import make_read_skill_tool, make_write_skill_tool

VALID = """---
name: hello-skill
description: Say hello
tools: [send_email]
---
Say hello to the owner.
"""


def registry(store, writes):
    reg = ToolRegistry()
    reg.register(make_read_skill_tool(store))
    reg.register(make_write_skill_tool(writes))
    return reg


async def test_write_skill_requires_approval_before_mutating_store():
    storage = MemoryStorage()
    store = SkillStore(storage)
    writes = SkillWriteService(store, storage)
    reg = registry(store, writes)
    out = json.loads(await reg.execute("write_skill", {"text": VALID}))
    assert out["queued"] is True
    assert out["approval"] == {"kind": "skill_write", "id": out["id"]}
    assert await store.get("hello-skill") is None

    assert await writes.approve(out["id"])
    assert (await store.get("hello-skill"))["status"] == "active"


async def test_write_skill_reports_parse_error():
    storage = MemoryStorage()
    store = SkillStore(storage)
    out = json.loads(await registry(store, SkillWriteService(store, storage)).execute(
        "write_skill", {"text": "garbage"}))
    assert "parse failed" in out["error"]


async def test_read_skill_returns_body_and_status():
    storage = MemoryStorage()
    store = SkillStore(storage)
    await store.save(VALID, source="agent")
    out = json.loads(await registry(store, SkillWriteService(store, storage)).execute(
        "read_skill", {"name": "hello-skill"}))
    assert out["body"].strip() == "Say hello to the owner."
    assert out["status"] == "pending" and out["tools"] == ["send_email"]


async def test_read_missing_skill_returns_error():
    storage = MemoryStorage()
    store = SkillStore(storage)
    out = json.loads(await registry(store, SkillWriteService(store, storage)).execute(
        "read_skill", {"name": "ghost"}))
    assert "not found" in out["error"]


async def test_agent_edit_leaves_active_version_untouched_until_approval():
    storage = MemoryStorage()
    store = SkillStore(storage)
    writes = SkillWriteService(store, storage)
    await store.save(VALID, source="repo")
    changed = VALID.replace("Say hello to the owner.", "Say hello twice.")

    proposal = await writes.propose(changed)
    assert (await store.get("hello-skill"))["body"].strip() == "Say hello to the owner."

    await writes.approve(proposal["id"])
    assert (await store.get("hello-skill"))["body"].strip() == "Say hello twice."

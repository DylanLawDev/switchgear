import json

from switchgear.config import Settings
from switchgear.scheduler import LocalScheduler
from switchgear.skills.store import SkillStore
from switchgear.storage.memory import MemoryStorage
from switchgear.tools.base import ToolRegistry
from switchgear.tools.schedule_tool import make_schedule_tool

S = Settings(_env_file=None, service_url="https://agent.example.com")

ACTIVE = """---
name: job-search
description: Search jobs
tools: [http_fetch]
---
Find jobs.
"""


async def build(storage):
    store = SkillStore(storage)
    reg = ToolRegistry()
    reg.register(make_schedule_tool(LocalScheduler(storage, S), store, storage))
    return store, reg


async def test_schedule_create_requires_active_skill():
    storage = MemoryStorage()
    store, reg = await build(storage)
    await store.save(ACTIVE, source="agent")  # pending
    out = json.loads(await reg.execute(
        "schedule", {"op": "create", "name": "job-search", "cron": "0 9 * * *"}))
    assert "only active" in out["error"]
    await store.set_status("job-search", "active")
    ok = json.loads(await reg.execute(
        "schedule", {"op": "create", "name": "job-search", "cron": "0 9 * * *"}))
    assert ok["ok"] is True
    audit = await storage.query("audit")
    assert any(a["tool"] == "schedule" and a["op"] == "create" for a in audit)


async def test_schedule_create_unknown_skill_errors():
    storage = MemoryStorage()
    _store, reg = await build(storage)
    out = json.loads(await reg.execute(
        "schedule", {"op": "create", "name": "ghost", "cron": "* * * * *"}))
    assert "not found" in out["error"]


async def test_schedule_list_and_delete():
    storage = MemoryStorage()
    store, reg = await build(storage)
    await store.save(ACTIVE, source="repo")  # active
    await reg.execute("schedule", {"op": "create", "name": "job-search", "cron": "0 9 * * *"})
    listed = json.loads(await reg.execute("schedule", {"op": "list"}))
    assert listed[0]["skill"] == "job-search"
    await reg.execute("schedule", {"op": "delete", "name": "job-search"})
    assert json.loads(await reg.execute("schedule", {"op": "list"})) == []

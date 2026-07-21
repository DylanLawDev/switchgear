import json

from switchgear.config import Settings
from switchgear.memory.embeddings import FakeEmbedder
from switchgear.memory.store import MemoryStore
from switchgear.skills.runner import SkillRunner, runner_prompt
from switchgear.skills.store import SkillStore
from switchgear.storage.memory import MemoryStorage
from switchgear.tools import build_registry
from tests.fakes import FakeGateway

S = Settings(_env_file=None, owner_email="me@example.com")

SKILL = """---
name: brief
description: Daily brief
tools: [storage]
---
Store a note then report done.
"""


class RecordingEmail:
    def __init__(self):
        self.sent = []

    async def send(self, to, subject, html):
        self.sent.append((to, subject, html))


def done_text(text):
    return [{"type": "text", "delta": text},
            {"type": "message", "usage": 7,
             "message": {"role": "assistant", "content": text}}]


async def runner(storage, gateway, email=None):
    store = SkillStore(storage)
    await store.save(SKILL, source="repo")  # active
    reg = build_registry(S, storage, gateway, skill_store=store)
    return store, SkillRunner(gateway, reg, store, S, storage, email)


async def test_run_writes_record_and_returns_summary():
    storage = MemoryStorage()
    gw = FakeGateway([done_text("all done")])
    _store, r = await runner(storage, gw)
    out = await r.run("brief", trigger="schedule")
    assert out["ok"] is True and out["skill"] == "brief"
    runs = await storage.query("runs")
    assert len(runs) == 1
    assert runs[0]["trigger"] == "schedule" and runs[0]["ok"] is True
    assert runs[0]["summary"] == "all done" and runs[0]["usage"] == 7


async def test_run_passes_tool_allowlist():
    storage = MemoryStorage()
    gw = FakeGateway([done_text("done")])
    _store, r = await runner(storage, gw)
    await r.run("brief")
    # the loop offered only the skill's allowlisted tool
    offered = [t["function"]["name"] for t in (gw.calls[0]["tools"] or [])]
    assert offered == ["storage"]


async def test_missing_or_inactive_skill_short_circuits():
    storage = MemoryStorage()
    store = SkillStore(storage)
    gw = FakeGateway([])
    r = SkillRunner(gw, build_registry(S, storage, gw, skill_store=store),
                    store, S, storage)
    assert (await r.run("ghost"))["error"] == "skill not found"
    await store.save(SKILL, source="agent")  # pending
    assert (await r.run("brief"))["error"] == "skill not active"


async def test_failed_run_records_error_and_emails_owner():
    storage = MemoryStorage()
    # budget of 1 forces a token-budget error after the first tool call
    s = Settings(_env_file=None, owner_email="me@example.com", run_token_budget=1)
    store = SkillStore(storage)
    await store.save(SKILL, source="repo")
    gw = FakeGateway([[{"type": "message", "usage": 10, "message": {
        "role": "assistant", "content": None, "tool_calls": [{"id": "c1",
        "type": "function", "function": {"name": "storage",
        "arguments": json.dumps({"op": "get", "collection": "x", "key": "y"})}}]}}]])
    email = RecordingEmail()
    r = SkillRunner(gw, build_registry(s, storage, gw, skill_store=store),
                    store, s, storage, email)
    out = await r.run("brief", trigger="schedule")
    assert out["ok"] is False
    assert (await storage.query("runs"))[0]["ok"] is False
    assert email.sent and "brief" in email.sent[0][1]


# ---------- standing instructions injection (storage layer phase 3) ----------

class ExplodingMemoryStore:
    async def core_block(self):
        raise RuntimeError("firestore down")


def test_runner_prompt_inserts_core_before_playbook_body():
    skill = {"name": "brief", "description": "Daily brief", "body": "PLAYBOOK BODY"}
    p = runner_prompt("me@example.com", skill, core_memories="- Always use metric units")
    assert "## Standing instructions (memories)\n- Always use metric units" in p
    assert p.index("Standing instructions") < p.index("PLAYBOOK BODY")


def test_runner_prompt_without_core_has_no_header():
    skill = {"name": "brief", "description": "Daily brief", "body": "PLAYBOOK BODY"}
    p = runner_prompt("me@example.com", skill)
    assert "## Standing instructions (memories)" not in p
    assert "PLAYBOOK BODY" in p


async def test_run_injects_core_block_from_memory_store():
    storage = MemoryStorage()
    gw = FakeGateway([done_text("done")])
    store = SkillStore(storage)
    await store.save(SKILL, source="repo")
    ms = MemoryStore(storage, FakeEmbedder(), S)
    await ms.save(text="Always use metric units", type="core", importance=8)
    r = SkillRunner(gw, build_registry(S, storage, gw, skill_store=store),
                    store, S, storage, memory_store=ms)
    out = await r.run("brief")
    assert out["ok"] is True
    sysmsg = gw.calls[0]["messages"][0]["content"]
    assert "## Standing instructions (memories)" in sysmsg
    assert "Always use metric units" in sysmsg


async def test_run_without_memory_store_still_works():
    storage = MemoryStorage()
    gw = FakeGateway([done_text("done")])
    _store, r = await runner(storage, gw)  # existing helper: no memory_store
    out = await r.run("brief")
    assert out["ok"] is True
    assert "## Standing instructions (memories)" not in gw.calls[0]["messages"][0]["content"]


async def test_run_survives_core_block_failure(caplog):
    storage = MemoryStorage()
    gw = FakeGateway([done_text("done")])
    store = SkillStore(storage)
    await store.save(SKILL, source="repo")
    r = SkillRunner(gw, build_registry(S, storage, gw, skill_store=store),
                    store, S, storage, memory_store=ExplodingMemoryStore())
    out = await r.run("brief")
    assert out["ok"] is True
    assert "## Standing instructions (memories)" not in gw.calls[0]["messages"][0]["content"]
    assert any("core memory block unavailable" in rec.message for rec in caplog.records)

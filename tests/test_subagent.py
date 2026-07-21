import json

from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.subagent import MAX_DEPTH, make_spawn_subagent_tool, subagent_depth
from switchgear.tools import build_registry
from switchgear.tools.base import Tool, ToolRegistry
from tests.fakes import FakeGateway

S = Settings(_env_file=None)


def final_text(text, usage=7):
    return [{"type": "text", "delta": text},
            {"type": "message", "usage": usage,
             "message": {"role": "assistant", "content": text}}]


def tool_call_msg(name, args):
    return {"type": "message", "usage": 5, "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": name, "arguments": json.dumps(args)}}]}}


class CrashingGateway:
    async def stream(self, tier, messages, tools=None):
        yield {"type": "text", "delta": "partial"}
        raise RuntimeError("boom")
        yield {}  # pragma: no cover - unreachable, keeps this an async generator


def registry_with(*names):
    reg = ToolRegistry()
    for name in names:
        async def _handler(**_kw):
            return {"ok": True}
        reg.register(Tool(name, f"{name} tool", {"type": "object", "properties": {}}, _handler))
    return reg


async def test_child_gets_only_requested_tools_intersected_with_registry():
    storage = MemoryStorage()
    gw = FakeGateway([final_text("all done")])
    reg = registry_with("echo", "storage")
    reg.register(make_spawn_subagent_tool(gw, reg, S, storage))
    tool = reg.get("spawn_subagent")

    out = await tool.handler(task="do the thing", tools=["echo", "not-a-real-tool"])

    offered = [t["function"]["name"] for t in gw.calls[0]["tools"]]
    assert offered == ["echo"]
    assert out == {"ok": True, "result": "all done", "usage": 7,
                   "tool_calls": [], "error": None}
    assert subagent_depth.get() == 0


async def test_unknown_tools_only_leaves_child_with_no_tools():
    storage = MemoryStorage()
    gw = FakeGateway([final_text("no tools needed")])
    reg = registry_with("echo")
    reg.register(make_spawn_subagent_tool(gw, reg, S, storage))
    tool = reg.get("spawn_subagent")

    out = await tool.handler(task="just answer", tools=["ghost-tool"])

    assert gw.calls[0]["tools"] is None  # empty allowlist -> no tools schema offered
    assert out["ok"] is True
    assert out["result"] == "no tools needed"


async def test_transcript_record_persisted():
    storage = MemoryStorage()
    gw = FakeGateway([final_text("summary text", usage=42)])
    reg = registry_with("echo")
    reg.register(make_spawn_subagent_tool(gw, reg, S, storage))
    tool = reg.get("spawn_subagent")

    out = await tool.handler(task="summarize X", tools=["echo"], context="extra info")

    assert out == {"ok": True, "result": "summary text", "usage": 42,
                   "tool_calls": [], "error": None}
    docs = await storage.query("subagents")
    assert len(docs) == 1
    doc = docs[0]
    assert doc["task"] == "summarize X"
    assert doc["tier"] == "chat"
    assert doc["tools"] == ["echo"]
    assert doc["ok"] is True
    assert doc["result"] == "summary text"
    assert doc["error"] is None
    assert doc["usage"] == 42
    assert isinstance(doc["at"], float)
    assert doc["messages"][0]["role"] == "system"
    assert "summarize X" in doc["messages"][1]["content"]
    assert "extra info" in doc["messages"][1]["content"]


async def test_depth_limit_refuses_directly_when_contextvar_at_limit():
    storage = MemoryStorage()
    gw = FakeGateway([])  # must never be called
    reg = registry_with("echo")
    reg.register(make_spawn_subagent_tool(gw, reg, S, storage))
    tool = reg.get("spawn_subagent")

    token = subagent_depth.set(MAX_DEPTH)
    try:
        out = await tool.handler(task="too deep", tools=["echo"])
    finally:
        subagent_depth.reset(token)

    assert out == {"error": "subagent depth limit reached"}
    assert gw.calls == []
    assert await storage.query("subagents") == []


async def test_depth_limit_via_registry_execute_mirrors_child_tool_result():
    # Integration-style: exercise the exact code path AgentLoop.run uses when a
    # child issues a scripted tool_call to spawn_subagent while already at the
    # depth ceiling — the JSON string returned here is what would be appended
    # to the child's own transcript as the tool result.
    storage = MemoryStorage()
    gw = FakeGateway([])
    reg = registry_with("echo")
    reg.register(make_spawn_subagent_tool(gw, reg, S, storage))

    token = subagent_depth.set(MAX_DEPTH)
    try:
        raw = await reg.execute("spawn_subagent", {"task": "nested", "tools": ["echo"]})
    finally:
        subagent_depth.reset(token)

    assert json.loads(raw) == {"error": "subagent depth limit reached"}
    assert gw.calls == []


async def test_child_may_spawn_once_more_but_grandchild_gets_no_spawn_tool():
    storage = MemoryStorage()
    gw = FakeGateway([
        # this call represents "root spawns child" -> the child's own loop:
        # iter 1: child spawns a grandchild
        [tool_call_msg("spawn_subagent", {"task": "grandchild task",
                                          "tools": ["spawn_subagent"]})],
        # grandchild's loop: no tools available (spawn_subagent was stripped)
        final_text("grandchild done"),
        # child's loop, iter 2: after receiving the grandchild's tool result
        final_text("child done"),
    ])
    reg = ToolRegistry()
    reg.register(make_spawn_subagent_tool(gw, reg, S, storage))
    tool = reg.get("spawn_subagent")

    out = await tool.handler(task="child task", tools=["spawn_subagent"])

    assert out == {"ok": True, "result": "child done", "usage": 12,
                   "tool_calls": ["spawn_subagent"], "error": None}
    docs = await storage.query("subagents")
    assert len(docs) == 2
    grandchild_doc = next(d for d in docs if d["task"] == "grandchild task")
    child_doc = next(d for d in docs if d["task"] == "child task")
    assert grandchild_doc["tools"] == []  # spawn_subagent excluded -> can't spawn further
    assert child_doc["tools"] == ["spawn_subagent"]
    assert subagent_depth.get() == 0


async def test_gateway_exception_still_writes_failed_record():
    storage = MemoryStorage()
    gw = CrashingGateway()
    reg = registry_with("echo")
    reg.register(make_spawn_subagent_tool(gw, reg, S, storage))
    tool = reg.get("spawn_subagent")

    out = await tool.handler(task="risky", tools=["echo"])

    assert out["ok"] is False
    assert "RuntimeError" in out["error"]
    assert out["result"] == "partial"
    docs = await storage.query("subagents")
    assert len(docs) == 1
    assert docs[0]["ok"] is False
    assert docs[0]["task"] == "risky"
    assert "RuntimeError" in docs[0]["error"]
    assert subagent_depth.get() == 0


async def test_build_registry_registers_spawn_subagent_unconditionally():
    storage = MemoryStorage()
    gw = FakeGateway([])
    reg = build_registry(S, storage, gw)
    assert reg.get("spawn_subagent").name == "spawn_subagent"

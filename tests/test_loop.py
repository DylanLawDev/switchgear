import json

import pytest

from switchgear.config import Settings
from switchgear.gateway import GatewayError
from switchgear.loop import AgentLoop
from switchgear.tools.base import Tool, ToolRegistry
from tests.fakes import FakeGateway

S = Settings(_env_file=None)


def registry_with_echo():
    async def echo(text: str) -> dict:
        return {"echo": text}

    reg = ToolRegistry()
    reg.register(Tool("echo", "echoes", {"type": "object", "properties": {
        "text": {"type": "string"}}, "required": ["text"]}, echo))
    return reg


def tool_call_msg(name, args):
    return {"type": "message", "usage": 10, "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": name, "arguments": json.dumps(args)}}]}}


async def collect(gen):
    return [e async for e in gen]


async def test_plain_text_run():
    gw = FakeGateway([[{"type": "text", "delta": "hi"},
                       {"type": "message", "usage": 5,
                        "message": {"role": "assistant", "content": "hi"}}]])
    events = await collect(AgentLoop(gw, registry_with_echo(), S).run(
        [{"role": "user", "content": "hey"}]))
    assert events[0] == {"type": "text", "delta": "hi"}
    assert events[-1]["type"] == "done" and events[-1]["usage"] == 5


async def test_tool_call_roundtrip():
    gw = FakeGateway([
        [tool_call_msg("echo", {"text": "yo"})],
        [{"type": "message", "usage": 5,
          "message": {"role": "assistant", "content": "done"}}],
    ])
    events = await collect(AgentLoop(gw, registry_with_echo(), S).run(
        [{"role": "user", "content": "go"}]))
    kinds = [e["type"] for e in events]
    assert kinds == ["tool_call", "tool_result", "done"]
    assert json.loads(events[1]["result"]) == {"echo": "yo"}
    # second gateway call got the tool transcript
    second = gw.calls[1]["messages"]
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "c1"
    assert events[-1]["usage"] == 15


async def test_budget_exhaustion():
    gw = FakeGateway([[tool_call_msg("echo", {"text": "x"})]])
    s = Settings(_env_file=None, run_token_budget=5)
    events = await collect(AgentLoop(gw, registry_with_echo(), s).run(
        [{"role": "user", "content": "go"}]))
    assert events[-1]["type"] == "error" and events[-1]["reason"] == "token budget exceeded"
    assert events[-1]["messages"][-1]["role"] == "assistant"


async def test_iteration_cap():
    s = Settings(_env_file=None, max_loop_iterations=2)
    gw = FakeGateway([[tool_call_msg("echo", {"text": "x"})],
                      [tool_call_msg("echo", {"text": "x"})]])
    events = await collect(AgentLoop(gw, registry_with_echo(), s).run(
        [{"role": "user", "content": "go"}]))
    assert events[-1]["type"] == "error" and events[-1]["reason"] == "iteration limit reached"
    assert events[-1]["messages"][-1]["role"] == "tool"


async def test_stream_without_final_message_raises_gateway_error():
    gw = FakeGateway([[{"type": "text", "delta": "hi"}]])  # no "message" event
    with pytest.raises(GatewayError):
        await collect(AgentLoop(gw, registry_with_echo(), S).run(
            [{"role": "user", "content": "hey"}]))


async def test_unknown_tool_name_returns_error_and_loop_continues():
    gw = FakeGateway([
        [tool_call_msg("does-not-exist", {})],
        [{"type": "message", "usage": 5,
          "message": {"role": "assistant", "content": "done"}}],
    ])
    events = await collect(AgentLoop(gw, registry_with_echo(), S).run(
        [{"role": "user", "content": "go"}]))
    kinds = [e["type"] for e in events]
    assert kinds == ["tool_call", "tool_result", "done"]
    assert "unknown tool" in json.loads(events[1]["result"])["error"]

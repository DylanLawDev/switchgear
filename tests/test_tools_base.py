import json

import pytest

from switchgear.tools.base import Tool, ToolNotAllowedError, ToolRegistry


def make_registry():
    async def add(a: int, b: int) -> dict:
        return {"sum": a + b}

    async def boom() -> str:
        raise RuntimeError("nope")

    reg = ToolRegistry()
    reg.register(Tool("add", "adds", {"type": "object", "properties": {
        "a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}, add))
    reg.register(Tool("boom", "fails", {"type": "object", "properties": {}}, boom))
    return reg


async def test_execute_and_schema():
    reg = make_registry()
    assert json.loads(await reg.execute("add", {"a": 2, "b": 3})) == {"sum": 5}
    schema = reg.schemas(["add"])
    assert len(schema) == 1 and schema[0]["function"]["name"] == "add"


async def test_allowlist_enforced():
    reg = make_registry()
    with pytest.raises(ToolNotAllowedError):
        await reg.execute("boom", {}, allowlist=["add"])


async def test_handler_error_returned_as_json():
    reg = make_registry()
    assert "nope" in json.loads(await reg.execute("boom", {}))["error"]


async def test_unknown_tool_returns_error_json_instead_of_raising():
    reg = make_registry()
    out = json.loads(await reg.execute("does-not-exist", {}))
    assert "unknown tool" in out["error"]


async def test_unserializable_result_returned_as_error_json():
    async def weird() -> set:
        return {1, 2, 3}  # sets aren't JSON serializable

    reg = make_registry()
    reg.register(Tool("weird", "weird", {"type": "object", "properties": {}}, weird))
    out = json.loads(await reg.execute("weird", {}))
    assert "error" in out

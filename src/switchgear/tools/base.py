import json
import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


class ToolNotAllowedError(Exception):
    pass


@dataclass(frozen=True)
class ExecutionPolicy:
    """Runtime capability boundary for a root agent or subagent.

    None means unrestricted. An explicit empty tuple means no access.
    Resource paths use provider/entity prefixes, e.g. resources/career-bank.
    """

    tools: tuple[str, ...] | None = None
    resources: tuple[str, ...] | None = None
    skills: tuple[str, ...] | None = None

    def allows_tool(self, name: str) -> bool:
        return self.tools is None or name in self.tools

    def allows_resource(self, path: str) -> bool:
        if self.resources is None:
            return True
        return any(path == rule or path.startswith(rule.rstrip("/") + "/")
                   for rule in self.resources)

    def allows_skill(self, name: str) -> bool:
        return self.skills is None or name in self.skills


current_policy: contextvars.ContextVar[ExecutionPolicy] = contextvars.ContextVar(
    "agent_execution_policy", default=ExecutionPolicy())
current_origin: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agent_execution_origin", default="chat")


@contextmanager
def use_policy(policy: ExecutionPolicy):
    token = current_policy.set(policy)
    try:
        yield
    finally:
        current_policy.reset(token)


@contextmanager
def use_origin(origin: str):
    token = current_origin.set(origin)
    try:
        yield
    finally:
        current_origin.reset(token)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Awaitable[Any]]
    effect: str = "read"
    idempotent: bool = True

    def openai_schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def schemas(self, allowlist: list[str] | None = None) -> list[dict]:
        policy = current_policy.get()
        names = allowlist if allowlist is not None else list(self._tools)
        names = [name for name in names if policy.allows_tool(name)]
        return [self._tools[n].openai_schema() for n in names if n in self._tools]

    async def execute(self, name: str, args: dict,
                      allowlist: list[str] | None = None) -> str:
        if allowlist is not None and name not in allowlist:
            raise ToolNotAllowedError(name)
        if not current_policy.get().allows_tool(name):
            raise ToolNotAllowedError(name)
        if name not in self._tools:
            return json.dumps({"error": f"unknown tool: {name}"})
        tool = self._tools[name]
        try:
            result = await tool.handler(**args)
            return result if isinstance(result, str) else json.dumps(result)
        except Exception as e:  # tool errors go back to the model, not up the stack
            return json.dumps({"error": f"{type(e).__name__}: {e}"})

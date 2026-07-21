import contextvars
import time
from uuid import uuid4

from switchgear.loop import AgentLoop
from switchgear.tools.base import Tool

MAX_DEPTH = 2

# Tracks how many spawn_subagent calls deep the current execution context is.
# 0 = the top-level agent (has not been spawned by anything).
# A handler invocation reads this to decide whether it may spawn a child, and
# sets it +1 for the duration of the child's own AgentLoop.run, so that a
# nested spawn_subagent call (invoked from within the child's loop) sees the
# correct depth.
subagent_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "subagent_depth", default=0)


def _subagent_system_prompt(tools: list[str]) -> str:
    available = ", ".join(tools) if tools else "none"
    return (
        "You are a scoped subagent. Complete the task and reply with your "
        f"final result as plain text. Tools available: {available}."
    )


def make_spawn_subagent_tool(gateway, registry, settings, storage) -> Tool:
    async def _spawn(task: str, tools: list[str], model_tier: str = "chat",
                     context: str | None = None) -> dict:
        depth = subagent_depth.get()
        if depth >= MAX_DEPTH:
            return {"error": "subagent depth limit reached"}

        registry_names = {t["function"]["name"] for t in registry.schemas()}
        child_allowlist = [t for t in tools if t in registry_names]
        if depth >= 1:
            child_allowlist = [t for t in child_allowlist if t != "spawn_subagent"]

        user_content = task if not context else f"{task}\n\n{context}"
        transcript = [
            {"role": "system", "content": _subagent_system_prompt(child_allowlist)},
            {"role": "user", "content": user_content},
        ]

        loop = AgentLoop(gateway, registry, settings)
        text, usage, tool_calls = "", 0, []
        ok, error = True, None
        token = subagent_depth.set(depth + 1)
        try:
            async for ev in loop.run(transcript, tier=model_tier,
                                     allowlist=child_allowlist):
                if ev["type"] == "text":
                    text += ev["delta"]
                elif ev["type"] == "tool_call":
                    tool_calls.append(ev["name"])
                elif ev["type"] == "done":
                    usage = ev["usage"]
                    transcript = ev["messages"]
                elif ev["type"] == "error":
                    ok, error = False, ev.get("reason", "subagent run error")
                    transcript = ev.get("messages", transcript)
        except Exception as e:  # a gateway/loop failure must still produce a record
            ok, error = False, f"{type(e).__name__}: {e}"
        finally:
            subagent_depth.reset(token)

        await storage.put("subagents", f"sub-{uuid4().hex}", {
            "task": task, "tier": model_tier, "tools": child_allowlist, "ok": ok,
            "usage": usage, "tool_calls": tool_calls, "result": text, "error": error,
            "at": time.time(), "messages": transcript})

        return {"ok": ok, "result": text, "usage": usage, "tool_calls": tool_calls,
                "error": error}

    return Tool(
        name="spawn_subagent",
        description=(
            "Spawn a scoped subagent to complete a delegated task. The child "
            "only receives the tools you list, intersected with the tools "
            "actually registered. Subagents may nest at most two levels deep "
            "(a spawned child may itself spawn one more level; grandchildren "
            "cannot spawn further). Returns the child's final text result, "
            "token usage, and the names of tools it called; the full "
            "transcript is persisted for later review."),
        parameters={"type": "object", "properties": {
            "task": {"type": "string", "description": "The task for the subagent to complete."},
            "tools": {"type": "array", "items": {"type": "string"},
                      "description": "Tool names to make available to the subagent."},
            "model_tier": {"type": "string", "enum": ["chat", "bulk", "writing"],
                          "description": "Model tier to run the subagent on."},
            "context": {"type": "string",
                       "description": "Optional extra background for the subagent."}},
            "required": ["task", "tools"]},
        handler=_spawn,
    )

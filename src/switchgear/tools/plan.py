"""Per-conversation planning checklist for multi-step agent work.

The chat worker binds ``plan_key_var`` to the conversation id for the
duration of a run, so plans persist across turns and the rebuilt system
prompt can re-inject the current checklist (see prompts.system_prompt).
"""

import contextvars
import time
from contextlib import contextmanager

from switchgear.storage.base import Storage
from switchgear.tools.base import Tool

COLLECTION = "plans"
MAX_TASKS = 30
MAX_TASK_CHARS = 300
MAX_TITLE_CHARS = 120
STATUSES = ("pending", "in_progress", "done", "skipped")
_GLYPHS = {"done": "x", "in_progress": ">", "pending": " ", "skipped": "-"}

plan_key_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "plan_key", default="adhoc")


@contextmanager
def use_plan_key(key: str):
    token = plan_key_var.set(key)
    try:
        yield
    finally:
        plan_key_var.reset(token)


def format_plan(plan: dict | None) -> str:
    if not plan or not plan.get("tasks"):
        return ""
    lines = [f"- [{_GLYPHS.get(t.get('status'), ' ')}] {t.get('text', '')}"
             for t in plan["tasks"]]
    title = plan.get("title") or "Plan"
    return f"{title}\n" + "\n".join(lines)


def _public(plan: dict) -> dict:
    return {"title": plan.get("title", ""), "tasks": plan.get("tasks", [])}


def make_plan_tool(storage: Storage) -> Tool:
    async def _plan(op: str, tasks: list | None = None, title: str = "",
                    index: int | None = None, status: str = "") -> dict:
        key = plan_key_var.get()
        if op == "set":
            if not isinstance(tasks, list) or not tasks:
                return {"error": "set requires a non-empty tasks list"}
            if len(tasks) > MAX_TASKS:
                return {"error": f"too many tasks (max {MAX_TASKS})"}
            cleaned = []
            for task in tasks:
                text = str(task).strip()
                if not text or len(text) > MAX_TASK_CHARS:
                    return {"error": f"each task must be 1-{MAX_TASK_CHARS} characters"}
                cleaned.append({"text": text, "status": "pending"})
            plan = {"title": str(title)[:MAX_TITLE_CHARS], "tasks": cleaned,
                    "updated_at": time.time()}
            await storage.put(COLLECTION, key, plan)
            return _public(plan)
        if op == "check":
            plan = await storage.get(COLLECTION, key)
            if plan is None:
                return {"error": "no plan set for this conversation; use op=set first"}
            if status not in STATUSES:
                return {"error": f"status must be one of {', '.join(STATUSES)}"}
            if not isinstance(index, int) or not 0 <= index < len(plan["tasks"]):
                return {"error": f"index must be 0-{len(plan['tasks']) - 1}"}
            plan["tasks"][index]["status"] = status
            plan["updated_at"] = time.time()
            plan.pop("_id", None)
            await storage.put(COLLECTION, key, plan)
            return _public(plan)
        if op == "read":
            plan = await storage.get(COLLECTION, key)
            return _public(plan) if plan else {"title": "", "tasks": []}
        return {"error": "op must be set, check, or read"}

    return Tool(
        name="plan",
        description=(
            "Maintain a task checklist for multi-step work in this conversation. "
            "op=set replaces the plan (tasks: list of strings, optional title); "
            "op=check updates one task (index, status: pending|in_progress|done|skipped); "
            "op=read returns the current plan. The current plan is shown to you every "
            "turn — keep it updated as you finish tasks."),
        parameters={
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": ["set", "check", "read"]},
                "tasks": {"type": "array", "items": {"type": "string"}},
                "title": {"type": "string"},
                "index": {"type": "integer"},
                "status": {"type": "string",
                           "enum": ["pending", "in_progress", "done", "skipped"]},
            },
            "required": ["op"],
        },
        handler=_plan,
        effect="write",
        idempotent=False,
    )

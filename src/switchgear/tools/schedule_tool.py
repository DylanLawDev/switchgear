import time
from uuid import uuid4

from switchgear.tools.base import Tool


def make_schedule_tool(scheduler, store, storage) -> Tool:
    async def _schedule(op: str, name: str | None = None, cron: str | None = None):
        if op == "list":
            return await scheduler.list()
        if op == "create":
            if not name or not cron:
                return {"error": "create requires name and cron"}
            skill = await store.get(name)
            if skill is None:
                return {"error": f"skill not found: {name}"}
            if skill["status"] != "active":
                return {"error": "only active skills can be scheduled"}
            doc = await scheduler.create(name=name, cron=cron, skill=name)
            await storage.put("audit", f"schedule-{uuid4().hex}", {
                "tool": "schedule", "op": "create", "skill": name,
                "cron": cron, "at": time.time()})
            return {"ok": True, "schedule": {"skill": doc["skill"], "cron": doc["cron"]}}
        if op == "delete":
            if not name:
                return {"error": "delete requires name"}
            await scheduler.delete(name)
            await storage.put("audit", f"schedule-{uuid4().hex}", {
                "tool": "schedule", "op": "delete", "skill": name, "at": time.time()})
            return {"ok": True}
        return {"error": f"unknown op: {op}"}

    return Tool(
        name="schedule",
        description=("Manage recurring skill runs. Ops: create (needs an active skill "
                     "name and a cron expression), list, delete."),
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["create", "list", "delete"]},
            "name": {"type": "string"}, "cron": {"type": "string"}},
            "required": ["op"]},
        handler=_schedule,
    )

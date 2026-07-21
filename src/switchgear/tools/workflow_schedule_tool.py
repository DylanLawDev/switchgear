from switchgear.tools.base import Tool


def make_workflow_schedule_tool(service) -> Tool:
    async def schedules(op: str, id: str = "", schedule: dict | None = None):
        if op == "list":
            return await service.list()
        if op == "get":
            return await service.get(id) or {"error": "schedule not found"}
        if op == "create":
            return await service.save(schedule or {}, source="agent")
        if op == "update":
            if not id:
                return {"error": "update requires id"}
            return await service.save(schedule or {}, schedule_id=id, source="agent")
        if op == "delete":
            return {"ok": await service.delete(id)}
        if op == "enable":
            return await service.set_enabled(id, True) or {"error": "schedule not found"}
        if op == "disable":
            return await service.set_enabled(id, False) or {"error": "schedule not found"}
        if op == "run":
            return await service.fire(id, trigger="agent")
        return {"error": f"unknown op: {op}"}

    return Tool(
        name="schedules",
        description=("Manage workflow schedules. A schedule targets an executable workflow and "
                     "uses either direct values or a prompt resolver."),
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["list", "get", "create", "update",
                                                    "delete", "enable", "disable", "run"]},
            "id": {"type": "string"}, "schedule": {"type": "object"}},
            "required": ["op"]},
        handler=schedules, effect="write", idempotent=False)

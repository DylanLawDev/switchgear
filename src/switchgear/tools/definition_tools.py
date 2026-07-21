from switchgear.tools.base import Tool


def make_agents_tool(store, writes) -> Tool:
    async def agents(op: str, name: str = "", text: str = ""):
        if op == "list":
            return await store.list()
        if op == "read":
            return await store.get(name) or {"error": "agent profile not found"}
        if op == "propose":
            return await writes.propose("agent", text)
        return {"error": f"unknown op: {op}"}
    return Tool("agents", "List, read, or propose an agent profile definition.",
                {"type": "object", "properties": {
                    "op": {"type": "string", "enum": ["list", "read", "propose"]},
                    "name": {"type": "string"}, "text": {"type": "string"}},
                 "required": ["op"]}, agents, effect="write", idempotent=False)


def make_workflows_tool(store, runner, writes) -> Tool:
    async def workflows(op: str, name: str = "", text: str = "",
                        inputs: dict | None = None):
        if op == "list":
            return await store.list()
        if op == "read":
            return await store.get(name) or {"error": "workflow not found"}
        if op == "propose":
            return await writes.propose("workflow", text)
        if op == "run":
            run = await runner.start(name, inputs or {}, trigger="agent")
            return await runner.dispatch(run["id"])
        return {"error": f"unknown op: {op}"}
    return Tool("workflows", "List, read, run, or propose workflow definitions.",
                {"type": "object", "properties": {
                    "op": {"type": "string", "enum": ["list", "read", "run", "propose"]},
                    "name": {"type": "string"}, "text": {"type": "string"},
                    "inputs": {"type": "object"}}, "required": ["op"]},
                workflows, effect="write", idempotent=False)


def make_channels_tool(store, writes) -> Tool:
    async def channels(op: str, name: str = "", text: str = ""):
        if op == "list":
            return await store.list()
        if op == "read":
            return await store.get(name) or {"error": "channel not found"}
        if op == "propose":
            return await writes.propose("channel", text)
        return {"error": f"unknown op: {op}"}
    return Tool("channels", "List, read, or propose channel definitions.",
                {"type": "object", "properties": {
                    "op": {"type": "string", "enum": ["list", "read", "propose"]},
                    "name": {"type": "string"}, "text": {"type": "string"}},
                 "required": ["op"]}, channels, effect="write", idempotent=False)

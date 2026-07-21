from switchgear.config import Settings
from switchgear.resources.agent_writes import AgentWriteService
from switchgear.resources.store import ResourceError, ResourceStore
from switchgear.tools.base import Tool, current_policy


def make_resources_tool(store: ResourceStore, settings: Settings,
                        writes: AgentWriteService | None = None) -> Tool:
    async def _run(op: str, name: str = "", offset: int = 0,
                   limit: int | None = None, kind: str = "",
                   description: str = "", content: str = ""):
        if op == "list":
            return [{"name": r["name"], "kind": r["kind"],
                     "description": r["description"], "size": r["size"]}
                    for r in await store.list()
                    if current_policy.get().allows_resource(
                        f"resources/{r['name']}")]
        if op == "read":
            if not current_policy.get().allows_resource(f"resources/{name}"):
                return {"error": f"resource access denied: {name}"}
            doc = await store.get(name)
            if doc is None:
                return {"error": f"unknown resource: {name}"}
            body = doc["content"]
            start = max(0, int(offset or 0))
            cap = settings.resource_read_chars
            window = cap if limit is None else max(0, min(int(limit), cap))
            return {"content": body[start:start + window], "size": doc["size"],
                    "kind": doc["kind"], "offset": start,
                    "total_chars": len(body)}
        if op in ("create", "update", "delete"):
            if not current_policy.get().allows_resource(f"resources/{name}"):
                return {"error": f"resource access denied: {name}"}
            if writes is None:
                return {"error": "resource writes are not enabled"}
            try:
                return await writes.propose(op, name, kind=kind,
                                            description=description,
                                            content=content)
            except ResourceError as e:
                return {"error": str(e)}
        return {"error": f"unknown op: {op}"}

    return Tool(
        name="resources",
        description=(
            "Read and (mode-permitting) write the owner's curated data banks. "
            "op='list' shows every resource; op='read' returns a character "
            f"window (max {settings.resource_read_chars} chars/call, "
            "'total_chars' gives the full length; pass 'offset'/'limit'). "
            "op='create'/'update'/'delete' change a resource: depending on the "
            "owner's write-mode setting the change applies immediately, is "
            "QUEUED for owner approval (result has queued=true — tell the "
            "owner it awaits their approval in Chat), or is "
            "refused. create needs name+kind+content; update keeps the stored "
            "kind/description unless given. Treat resources as the owner's "
            "ground truth; never overwrite content you haven't read first."),
        parameters={"type": "object", "properties": {
            "op": {"type": "string",
                   "enum": ["list", "read", "create", "update", "delete"]},
            "name": {"type": "string", "description": "resource name"},
            "offset": {"type": "integer",
                       "description": "start character offset (op=read)"},
            "limit": {"type": "integer",
                      "description": "max characters to return (op=read)"},
            "kind": {"type": "string",
                     "description": "csv|json|md|txt (op=create)"},
            "description": {"type": "string",
                            "description": "one-line description (create/update)"},
            "content": {"type": "string",
                        "description": "full new content (create/update)"}},
            "required": ["op"]},
        handler=_run,
    )

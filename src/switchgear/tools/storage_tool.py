from switchgear.storage.base import Storage
from switchgear.tools.base import Tool

# Owner-curated collections have dedicated stores (ResourceStore, etc.) that
# enforce validation and audit logging. The raw storage tool must not be able
# to write to them directly — see spec §7.3. "memories" is pre-registered for
# the phase-2 collection even though nothing writes it yet. "resource-settings"
# (agent write-mode) and "resource-pending" (the approval queue) are protected
# so the agent cannot self-escalate its own write privileges or forge pending
# edits — only AgentWriteService may write them.
PROTECTED_COLLECTIONS = {"resources", "memories", "audit", "resource-settings",
                          "resource-pending", "skill-pending", "definition-pending",
                          "agent-profiles", "workflows", "channels", "workflow-schedules",
                          "app-settings"}


def make_storage_tool(storage: Storage) -> Tool:
    async def _storage(op: str, collection: str, key: str | None = None,
                       doc: dict | None = None, where: dict | None = None,
                       limit: int | None = None):
        if op in {"put", "delete"} and collection in PROTECTED_COLLECTIONS:
            return {"error": f"collection '{collection}' is owner-managed and "
                              "read-only for this tool"}
        if op == "get":
            result = await storage.get(collection, key)
            if result is not None and collection in PROTECTED_COLLECTIONS:
                result.pop("embedding", None)
            return result
        if op == "put":
            await storage.put(collection, key, doc or {})
            return {"ok": True}
        if op == "delete":
            await storage.delete(collection, key)
            return {"ok": True}
        if op == "query":
            results = await storage.query(collection, where=where, limit=limit)
            if collection in PROTECTED_COLLECTIONS:
                for r in results:
                    r.pop("embedding", None)
            return results
        raise ValueError(f"unknown op {op}")

    return Tool(
        name="storage",
        description=(
            "Persistent document store. Ops: get/put/delete/query over named "
            "collections. The owner-managed collections "
            f"({', '.join(sorted(PROTECTED_COLLECTIONS))}) are read-only here "
            "(get/query only) — use their dedicated tools to write them."),
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["get", "put", "delete", "query"]},
            "collection": {"type": "string"},
            "key": {"type": "string"},
            "doc": {"type": "object"},
            "where": {"type": "object"},
            "limit": {"type": "integer"}},
            "required": ["op", "collection"]},
        handler=_storage,
    )

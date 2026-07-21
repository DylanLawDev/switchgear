"""Generic intake tool: skills save items into a workflow with schema
validation and dedup-by-construction (key derives from the source identity),
so playbooks never reason about "have I seen this before".

`save_item` is the single validated intake path — the workflow_items tool
derives its key from url/title; the channel ingest pipeline supplies a
deterministic msg-<hash> key. Both get identical field validation."""

import hashlib
import time

from switchgear.tools.base import Tool


async def save_item(workflow_store, storage, workflow: str, item: dict,
                    *, key: str | None = None) -> dict:
    wf = await workflow_store.get(workflow)
    if wf is None or wf.get("status") != "active":
        return {"error": f"workflow not found or inactive: {workflow}"}
    items = wf["items"]
    declared = set(items["fields"])
    unknown = sorted(k for k in item if k not in declared)
    if unknown:
        return {"error": f"unknown fields: {', '.join(unknown)}"}
    if key is None:
        basis = item.get("url") or item.get(items["title_field"])
        if not basis:
            return {"error": "item needs a url or title to derive its key"}
        key = f"itm-{hashlib.sha256(str(basis).encode()).hexdigest()[:16]}"
    if await storage.get(items["collection"], key) is not None:
        return {"status": "seen", "key": key}
    record = {**{k: v for k, v in item.items() if k in declared},
              items["key_field"]: key}
    for fname, fdef in items["fields"].items():
        if fdef["type"] == "timestamp" and record.get(fname) is None:
            record[fname] = time.time()
    await storage.put(items["collection"], key, record)
    return {"status": "new", "key": key}


def make_workflow_items_tool(workflow_store, storage) -> Tool:
    async def _handler(op: str, workflow: str, item: dict | None = None) -> dict:
        if op == "save":
            return await save_item(workflow_store, storage, workflow, item or {})
        return {"error": f"unknown op: {op}"}

    return Tool(
        name="workflow_items",
        description=(
            "Save an intake item into a workflow's items collection. Items are "
            "deduplicated by url (or title): saving the same source twice returns "
            'status "seen" instead of writing a duplicate. Only fields declared '
            "in the workflow definition are accepted; missing timestamp fields "
            "are stamped automatically."),
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["save"],
                   "description": "Operation to perform."},
            "workflow": {"type": "string",
                         "description": "Name of the target workflow."},
            "item": {"type": "object",
                     "description": "Field values for the item, per the "
                                    "workflow's declared item fields."}},
            "required": ["op", "workflow"]},
        handler=_handler,
    )

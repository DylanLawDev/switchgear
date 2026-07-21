import json

from switchgear.storage.memory import MemoryStorage
from switchgear.tools.workflow_items import make_workflow_items_tool, save_item
from switchgear.workflows.store import WorkflowStore

RESEARCH = """---
schema_version: 1
name: research
description: research workflow
items:
  label: source
  label_plural: sources
  title_field: title
  fields:
    title:    {type: text}
    url:      {type: url}
    topic:    {type: enum}
    score:    {type: score, max: 100}
    summary:  {type: markdown}
    found_at: {type: timestamp}
  list_fields: [title, topic, score, found_at]
  sort: [-score, -found_at]
intake:
  skills: [research-watch]
---
Body.
"""

ITEM = {"title": "Agents in prod", "url": "https://example.com/a",
        "topic": "agents", "score": 80, "summary": "A useful writeup."}


async def make_tool():
    storage = MemoryStorage()
    store = WorkflowStore(storage, generators=set(), executors=set())
    await store.save(RESEARCH, source="repo")
    return make_workflow_items_tool(store, storage), storage, store


async def call(tool, **args):
    raw = await tool.handler(**args)
    return raw if isinstance(raw, dict) else json.loads(raw)


async def test_save_new_item_stamps_timestamp_and_keys_by_url():
    tool, storage, _ = await make_tool()
    out = await call(tool, op="save", workflow="research", item=dict(ITEM))
    assert out["status"] == "new"
    assert out["key"].startswith("itm-")
    stored = await storage.get("wf-research-items", out["key"])
    assert stored["title"] == "Agents in prod"
    assert isinstance(stored["found_at"], float)   # stamped, not supplied
    assert stored["key"] == out["key"]


async def test_save_dedups_by_url():
    tool, _, _ = await make_tool()
    first = await call(tool, op="save", workflow="research", item=dict(ITEM))
    second = await call(tool, op="save", workflow="research",
                        item={**ITEM, "score": 99})
    assert second == {"status": "seen", "key": first["key"]}


async def test_save_rejects_undeclared_fields():
    tool, _, _ = await make_tool()
    out = await call(tool, op="save", workflow="research",
                     item={**ITEM, "sneaky": "x"})
    assert "unknown fields" in out["error"]


async def test_save_requires_url_or_title():
    tool, _, _ = await make_tool()
    out = await call(tool, op="save", workflow="research", item={"score": 5})
    assert "url or title" in out["error"]


async def test_save_rejects_unknown_or_inactive_workflow():
    tool, _, store = await make_tool()
    assert "not found" in (await call(tool, op="save", workflow="nope",
                                      item=dict(ITEM)))["error"]
    await store.set_status("research", "pending")
    assert "not found" in (await call(tool, op="save", workflow="research",
                                      item=dict(ITEM)))["error"]


async def test_unknown_op_errors():
    tool, _, _ = await make_tool()
    assert "unknown op" in (await call(tool, op="delete", workflow="research"))["error"]


async def test_derived_key_wins_over_declared_item_field():
    """Verify that derived key always wins even if workflow declares a 'key' field."""
    # Create a workflow where items declare a field named 'key'
    workflow_with_key_field = """---
schema_version: 1
name: keyed-workflow
description: workflow with key field
items:
  label: item
  label_plural: items
  title_field: url
  fields:
    key:      {type: text}
    url:      {type: url}
    created_at: {type: timestamp}
  list_fields: [url]
  sort: [-created_at]
intake:
  skills: []
---
Body.
"""
    storage = MemoryStorage()
    store = WorkflowStore(storage, generators=set(), executors=set())
    await store.save(workflow_with_key_field, source="repo")
    tool = make_workflow_items_tool(store, storage)

    # Try to hijack the key with an LLM-supplied value
    item = {"key": "hijack", "url": "https://example.com/test"}
    out = await call(tool, op="save", workflow="keyed-workflow", item=item)

    assert out["status"] == "new"
    derived_key = out["key"]
    assert derived_key.startswith("itm-")
    assert derived_key != "hijack"

    # Fetch by the derived key and verify it's actually stored with that key
    stored = await storage.get("wf-keyed-workflow-items", derived_key)
    assert stored is not None
    # The key field in the record should be the derived key, not the hijacked value
    assert stored["key"] == derived_key


# ---------- save_item with an explicit key (the channel ingest path) ----------


async def test_save_item_with_explicit_key_stores_under_it():
    _, storage, store = await make_tool()
    out = await save_item(store, storage, "research",
                          {"title": "Keyed", "summary": "s"}, key="msg-abc")
    assert out == {"status": "new", "key": "msg-abc"}
    stored = await storage.get("wf-research-items", "msg-abc")
    assert stored["title"] == "Keyed"
    assert stored["key"] == "msg-abc"
    assert isinstance(stored["found_at"], float)   # stamped, not supplied


async def test_save_item_with_explicit_key_dedupes():
    _, storage, store = await make_tool()
    await save_item(store, storage, "research", {"title": "Keyed"}, key="msg-abc")
    out = await save_item(store, storage, "research", {"title": "Again"},
                          key="msg-abc")
    assert out == {"status": "seen", "key": "msg-abc"}


async def test_save_item_with_explicit_key_still_validates_fields():
    _, storage, store = await make_tool()
    out = await save_item(store, storage, "research", {"sneaky": "x"},
                          key="msg-abc")
    assert "unknown fields" in out["error"]
    assert await storage.get("wf-research-items", "msg-abc") is None


async def test_save_item_rejects_inactive_workflow_with_explicit_key():
    _, storage, store = await make_tool()
    await store.set_status("research", "pending")
    out = await save_item(store, storage, "research", {"title": "T"}, key="msg-abc")
    assert "not found" in out["error"]

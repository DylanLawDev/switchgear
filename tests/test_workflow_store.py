import time

from switchgear.storage.memory import MemoryStorage
from switchgear.workflows.store import WorkflowStore


MINIMAL = """---
schema_version: 1
name: test-flow
description: a test workflow
items:
  label: thing
  label_plural: things
  title_field: title
  fields:
    title: {type: text}
intake:
  skills: []
---
Body text.
"""

BROKEN = MINIMAL.replace("schema_version: 1", "schema_version: 9")


def store(**kw):
    kw.setdefault("generators", set())
    kw.setdefault("executors", set())
    return WorkflowStore(MemoryStorage(), **kw)


async def test_retention_purge_is_a_store_lifecycle_operation():
    storage = MemoryStorage()
    workflow_store = WorkflowStore(storage, generators=set(), executors=set())
    workflow = {
        "items": {
            "collection": "items", "key_field": "key", "retention": 10,
            "fields": {"created_at": {"type": "timestamp"}},
        }
    }
    await storage.put("items", "old", {"key": "old", "created_at": time.time() - 11})
    await storage.put("items", "new", {"key": "new", "created_at": time.time()})

    assert await workflow_store.purge_expired_items(workflow) == 1
    assert await storage.get("items", "old") is None
    assert await storage.get("items", "new") is not None


async def test_save_repo_source_is_active_and_get_roundtrips():
    s = store()
    saved = await s.save(MINIMAL, source="repo")
    assert saved["status"] == "active"
    got = await s.get("test-flow")
    assert got["name"] == "test-flow"
    assert got["items"]["title_field"] == "title"
    assert got["body"] == "Body text.\n" or got["body"] == "Body text."


async def test_save_agent_source_is_pending():
    s = store()
    saved = await s.save(MINIMAL, source="agent")
    assert saved["status"] == "pending"


async def test_list_returns_summaries_sorted():
    s = store()
    await s.save(MINIMAL, source="repo")
    rows = await s.list()
    assert rows == [{"name": "test-flow", "description": "a test workflow",
                     "ui_home": "workflows",
                     "status": "active", "source": "repo"}]


async def test_set_status():
    s = store()
    await s.save(MINIMAL, source="agent")
    doc = await s.set_status("test-flow", "active")
    assert doc["status"] == "active"
    assert await s.set_status("missing", "active") is None


async def test_seed_dir_loads_valid_and_skips_invalid(tmp_path):
    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "WORKFLOW.md").write_text(MINIMAL)
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "WORKFLOW.md").write_text(BROKEN)
    s = store()
    count = await s.seed_dir(str(tmp_path))
    assert count == 1
    assert await s.get("test-flow") is not None


async def test_seed_dir_missing_path_returns_zero():
    assert await store().seed_dir("/does/not/exist") == 0


async def test_seed_dir_does_not_overwrite_existing(tmp_path):
    (tmp_path / "flow").mkdir()
    (tmp_path / "flow" / "WORKFLOW.md").write_text(MINIMAL)
    s = store()
    await s.save(MINIMAL, source="repo")
    await s.set_status("test-flow", "disabled")
    count = await s.seed_dir(str(tmp_path))
    assert count == 0
    assert (await s.get("test-flow"))["status"] == "disabled"


CHANGED = MINIMAL.replace("description: a test workflow",
                          "description: a changed test workflow")


async def test_seed_dir_refreshes_changed_repo_definition_preserving_status(tmp_path):
    (tmp_path / "flow").mkdir()
    wf_file = tmp_path / "flow" / "WORKFLOW.md"
    wf_file.write_text(MINIMAL)
    s = store()
    await s.seed_dir(str(tmp_path))
    assert (await s.get("test-flow"))["status"] == "active"

    wf_file.write_text(CHANGED)
    count = await s.seed_dir(str(tmp_path))
    assert count == 1
    doc = await s.get("test-flow")
    assert doc["description"] == "a changed test workflow"
    assert doc["status"] == "active"
    assert doc["source"] == "repo"


async def test_seed_dir_refreshes_changed_definition_but_preserves_disabled_status(tmp_path):
    (tmp_path / "flow").mkdir()
    wf_file = tmp_path / "flow" / "WORKFLOW.md"
    wf_file.write_text(MINIMAL)
    s = store()
    await s.seed_dir(str(tmp_path))
    await s.set_status("test-flow", "disabled")

    wf_file.write_text(CHANGED)
    count = await s.seed_dir(str(tmp_path))
    assert count == 1
    doc = await s.get("test-flow")
    assert doc["description"] == "a changed test workflow"
    assert doc["status"] == "disabled"

from pathlib import Path

from switchgear.skills.store import SkillStore
from switchgear.storage.memory import MemoryStorage
from switchgear.workflows.store import WorkflowStore


WORKFLOW_TEXT = """---
schema_version: 1
name: my-private-flow
description: tenant-owned workflow
items:
  label: Item
  label_plural: Items
  title_field: title
  fields:
    title: {type: text}
---
Private tenant workflow.
"""

SKILL_TEXT = """---
name: my-private-skill
description: tenant-owned skill
---
Do the private thing.
"""


def write_workflow_dir(root: Path, name: str, text: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "WORKFLOW.md").write_text(text)
    return root


async def test_user_workflow_seeds_active_with_owner_source(tmp_path):
    store = WorkflowStore(MemoryStorage(), generators=set(), executors=set())
    write_workflow_dir(tmp_path / "workflows", "my-private-flow", WORKFLOW_TEXT)
    seeded = await store.seed_dir(str(tmp_path / "workflows"), source="owner")
    assert seeded == 1
    doc = await store.get("my-private-flow")
    assert doc["source"] == "owner"
    assert doc["status"] == "active"


async def test_repo_reseed_does_not_touch_owner_sourced_doc(tmp_path):
    store = WorkflowStore(MemoryStorage(), generators=set(), executors=set())
    write_workflow_dir(tmp_path / "user", "my-private-flow", WORKFLOW_TEXT)
    await store.seed_dir(str(tmp_path / "user"), source="owner")

    changed = WORKFLOW_TEXT.replace("tenant-owned workflow", "repo takeover attempt")
    write_workflow_dir(tmp_path / "repo", "my-private-flow", changed)
    seeded = await store.seed_dir(str(tmp_path / "repo"), source="repo")
    assert seeded == 0
    doc = await store.get("my-private-flow")
    assert doc["source"] == "owner"
    assert "repo takeover" not in doc["text"]


async def test_owner_reseed_refreshes_changed_owner_doc(tmp_path):
    store = WorkflowStore(MemoryStorage(), generators=set(), executors=set())
    write_workflow_dir(tmp_path / "user", "my-private-flow", WORKFLOW_TEXT)
    await store.seed_dir(str(tmp_path / "user"), source="owner")

    updated = WORKFLOW_TEXT.replace("tenant-owned workflow", "tenant-owned v2")
    (tmp_path / "user" / "my-private-flow" / "WORKFLOW.md").write_text(updated)
    seeded = await store.seed_dir(str(tmp_path / "user"), source="owner")
    assert seeded == 1
    doc = await store.get("my-private-flow")
    assert doc["description"] == "tenant-owned v2"
    assert doc["source"] == "owner"


async def test_missing_user_dir_is_noop(tmp_path):
    store = WorkflowStore(MemoryStorage(), generators=set(), executors=set())
    assert await store.seed_dir(str(tmp_path / "nope"), source="owner") == 0


async def test_user_skill_seeds_with_owner_source(tmp_path):
    store = SkillStore(MemoryStorage())
    d = tmp_path / "skills" / "my-private-skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(SKILL_TEXT)
    seeded = await store.seed_dir(str(tmp_path / "skills"), source="owner")
    assert seeded == 1
    doc = await store.get("my-private-skill")
    assert doc["source"] == "owner"
    # insert-only: a second seed with different text does not overwrite
    (d / "SKILL.md").write_text(SKILL_TEXT.replace("Do the private thing.", "changed"))
    assert await store.seed_dir(str(tmp_path / "skills"), source="owner") == 0

import pytest

from switchgear.skills.model import SkillParseError
from switchgear.skills.store import SkillStore
from switchgear.storage.memory import MemoryStorage

REPO_SKILL = """---
name: repo-skill
description: A repo skill
tools: [http_fetch]
---
Do the thing.
"""

SWITCHGEAR_SKILL = """---
name: agent-skill
description: An agent skill
tools: [storage]
---
Do another thing.
"""


def store():
    return SkillStore(MemoryStorage())


async def test_repo_source_is_active_agent_source_is_pending():
    s = store()
    assert (await s.save(REPO_SKILL, source="repo"))["status"] == "active"
    assert (await s.save(SWITCHGEAR_SKILL, source="agent"))["status"] == "pending"


async def test_agent_edit_of_active_skill_reverts_to_pending():
    s = store()
    await s.save(REPO_SKILL, source="repo")
    await s.set_status("repo-skill", "active")
    edited = REPO_SKILL.replace("Do the thing.", "Do the thing differently.")
    saved = await s.save(edited, source="agent")
    assert saved["status"] == "pending"
    assert (await s.get("repo-skill"))["body"].strip() == "Do the thing differently."


async def test_save_propagates_parse_error():
    with pytest.raises(SkillParseError):
        await store().save("not a skill", source="agent")


async def test_list_summaries_sorted_without_body():
    s = store()
    await s.save(SWITCHGEAR_SKILL, source="agent")
    await s.save(REPO_SKILL, source="repo")
    listed = await s.list()
    assert [d["name"] for d in listed] == ["agent-skill", "repo-skill"]
    assert "body" not in listed[0]
    assert listed[1] == {"name": "repo-skill", "description": "A repo skill",
                         "status": "active", "source": "repo", "schedule": None}


async def test_set_status_missing_returns_none():
    assert await store().set_status("nope", "active") is None


async def test_seed_dir_seeds_absent_only(tmp_path):
    d = tmp_path / "brief"
    d.mkdir()
    (d / "SKILL.md").write_text(REPO_SKILL.replace("repo-skill", "brief"))
    s = store()
    assert await s.seed_dir(str(tmp_path)) == 1
    assert (await s.get("brief"))["status"] == "active"
    # a re-seed does not clobber an owner-modified copy
    await s.save(REPO_SKILL.replace("repo-skill", "brief"), source="agent")  # -> pending
    assert await s.seed_dir(str(tmp_path)) == 0
    assert (await s.get("brief"))["status"] == "pending"


async def test_seed_dir_missing_path_is_noop(tmp_path):
    assert await store().seed_dir(str(tmp_path / "does-not-exist")) == 0

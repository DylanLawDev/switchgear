import json

import pytest

from switchgear.config import Settings
from switchgear.resources.store import (
    ResourceError,
    ResourceStore,
    make_bank_provider,
)
from switchgear.storage.memory import MemoryStorage

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")


def store(settings=S, storage=None):
    return ResourceStore(storage or MemoryStorage(), settings)


# ---------- save: validation matrix ----------


async def test_save_and_get_roundtrip():
    s = store()
    doc = await s.save("notes", "md", "team notes", "# Notes\nhello")
    assert doc["name"] == "notes"
    assert doc["kind"] == "md"
    assert doc["description"] == "team notes"
    assert doc["size"] == len("# Notes\nhello".encode())
    assert doc["source"] == "user"
    assert doc["created_at"] <= doc["updated_at"]
    got = await s.get("notes")
    assert got["content"] == "# Notes\nhello"


async def test_save_rejects_bad_names():
    s = store()
    for bad in ("Bad Name", "UPPER", "-leading-dash", "", "a" * 65):
        with pytest.raises(ResourceError, match="name"):
            await s.save(bad, "md", "", "x")


async def test_save_rejects_name_with_trailing_newline():
    s = store()
    for bad in ("notes\n", "notes\nx"):
        with pytest.raises(ResourceError, match="name"):
            await s.save(bad, "md", "", "x")


async def test_save_rejects_unknown_kind():
    s = store()
    with pytest.raises(ResourceError, match="kind"):
        await s.save("notes", "exe", "", "x")


async def test_save_rejects_invalid_json():
    s = store()
    with pytest.raises(ResourceError, match="json"):
        await s.save("data", "json", "", "not json at all")


async def test_save_accepts_valid_json():
    s = store()
    doc = await s.save("data", "json", "", '{"ok": true}')
    assert doc["kind"] == "json"


async def test_save_rejects_ragged_csv():
    s = store()
    with pytest.raises(ResourceError, match="csv"):
        await s.save("table", "csv", "", "a,b,c\n1,2\n")


async def test_save_accepts_valid_csv():
    s = store()
    doc = await s.save("table", "csv", "", "a,b,c\n1,2,3\n4,5,6\n")
    assert doc["kind"] == "csv"


async def test_save_rejects_empty_csv():
    s = store()
    with pytest.raises(ResourceError, match="csv"):
        await s.save("table", "csv", "", "")


async def test_save_rejects_oversize_content():
    small = Settings(_env_file=None, owner_email="me@example.com",
                     session_secret="s3", resource_max_bytes=10)
    s = store(settings=small)
    with pytest.raises(ResourceError, match="byte"):
        await s.save("notes", "md", "", "x" * 11)
    # exactly at the limit is fine
    doc = await s.save("notes", "md", "", "x" * 10)
    assert doc["size"] == 10


async def test_kind_is_immutable_after_creation():
    s = store()
    await s.save("notes", "md", "", "# hi")
    with pytest.raises(ResourceError, match="immutable"):
        await s.save("notes", "txt", "", "plain now")
    # same kind updates fine
    doc = await s.save("notes", "md", "new description", "# v2")
    assert doc["content"] == "# v2"
    assert doc["description"] == "new description"


async def test_update_preserves_created_at():
    s = store()
    first = await s.save("notes", "md", "", "v1")
    second = await s.save("notes", "md", "", "v2")
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] >= first["updated_at"]


async def test_reserved_names_rejected():
    s = store()
    for name in ("settings", "pending"):
        with pytest.raises(ResourceError, match="reserved"):
            await s.save(name, "md", "", "x")


# ---------- validate ----------


async def test_validate_checks_without_writing():
    s = store()
    with pytest.raises(ResourceError):
        await s.validate("notes", "json", "not json")
    assert await s.validate("notes", "md", "# ok") is None  # nothing exists
    assert await s.get("notes") is None                      # and nothing was written


async def test_validate_returns_existing_doc():
    s = store()
    saved = await s.save("notes", "md", "", "v1")
    existing = await s.validate("notes", "md", "v2")
    assert existing == saved


async def test_validate_rejects_reserved_names():
    s = store()
    for name in ("settings", "pending"):
        with pytest.raises(ResourceError, match="reserved"):
            await s.validate(name, "md", "x")


# ---------- get / list / delete ----------


async def test_get_missing_returns_none():
    assert await store().get("nope") is None


async def test_list_returns_summaries_sorted_without_content():
    s = store()
    await s.save("zeta", "txt", "last", "zzz")
    await s.save("alpha", "md", "first", "aaa")
    rows = await s.list()
    assert [r["name"] for r in rows] == ["alpha", "zeta"]
    assert rows[0] == {"name": "alpha", "kind": "md", "description": "first",
                       "size": 3, "source": "user",
                       "updated_at": rows[0]["updated_at"]}
    assert "content" not in rows[0]


async def test_list_skips_malformed_docs(caplog):
    storage = MemoryStorage()
    s = store(storage=storage)
    await s.save("good", "md", "fine", "content")
    await storage.put("resources", "junk-no-name", {"kind": "md", "description": "",
                                                     "size": 0, "source": "seed",
                                                     "updated_at": 1.0})
    await storage.put("resources", "junk-no-kind", {"name": "junk", "description": "",
                                                     "size": 0, "source": "seed",
                                                     "updated_at": 1.0})
    with caplog.at_level("DEBUG"):
        rows = await s.list()
    assert [r["name"] for r in rows] == ["good"]


async def test_delete_roundtrip_and_missing():
    s = store()
    await s.save("notes", "md", "", "x")
    assert await s.delete("notes") is True
    assert await s.get("notes") is None
    assert await s.delete("notes") is False


# ---------- audit ----------


async def test_save_and_delete_are_audited():
    storage = MemoryStorage()
    s = store(storage=storage)
    await s.save("notes", "md", "", "x")
    await s.delete("notes")
    audit = await storage.query("audit")
    actions = [(a["action"], a["name"]) for a in audit]
    assert ("resource_save", "notes") in actions
    assert ("resource_delete", "notes") in actions
    assert all(isinstance(a["at"], float) for a in audit)


async def test_failed_save_is_not_audited():
    storage = MemoryStorage()
    s = store(storage=storage)
    with pytest.raises(ResourceError):
        await s.save("data", "json", "", "not json")
    assert await storage.query("audit") == []


# ---------- seed_dir ----------


async def test_seed_dir_inserts_files_and_reads_meta(tmp_path):
    (tmp_path / "notes.md").write_text("# Notes\n")
    (tmp_path / "notes.meta.yaml").write_text("description: my notes\n")
    (tmp_path / "table.csv").write_text("a,b\n1,2\n")
    s = store()
    assert await s.seed_dir(str(tmp_path)) == 2
    doc = await s.get("notes")
    assert doc["kind"] == "md"
    assert doc["source"] == "seed"
    assert doc["description"] == "my notes"
    assert (await s.get("table"))["kind"] == "csv"


async def test_seed_dir_missing_path_returns_zero():
    assert await store().seed_dir("/does/not/exist") == 0


async def test_seed_dir_is_idempotent(tmp_path):
    (tmp_path / "notes.md").write_text("v1")
    s = store()
    assert await s.seed_dir(str(tmp_path)) == 1
    assert await s.seed_dir(str(tmp_path)) == 0


async def test_seed_dir_updates_seed_sourced_doc_when_content_changes(tmp_path):
    (tmp_path / "notes.md").write_text("v1")
    s = store()
    await s.seed_dir(str(tmp_path))
    (tmp_path / "notes.md").write_text("v2")
    assert await s.seed_dir(str(tmp_path)) == 1
    doc = await s.get("notes")
    assert doc["content"] == "v2"
    assert doc["source"] == "seed"


async def test_seed_dir_never_overwrites_user_edits(tmp_path):
    (tmp_path / "notes.md").write_text("v1")
    s = store()
    await s.seed_dir(str(tmp_path))
    await s.save("notes", "md", "", "owner edit", source="user")
    (tmp_path / "notes.md").write_text("v2")
    assert await s.seed_dir(str(tmp_path)) == 0
    doc = await s.get("notes")
    assert doc["content"] == "owner edit"
    assert doc["source"] == "user"


async def test_seed_dir_tolerates_non_mapping_meta(tmp_path):
    (tmp_path / "notes.md").write_text("# Notes\n")
    (tmp_path / "notes.meta.yaml").write_text("just a string\n")
    s = store()
    assert await s.seed_dir(str(tmp_path)) == 1
    doc = await s.get("notes")
    assert doc["content"] == "# Notes\n"
    assert doc["description"] == ""


async def test_seed_dir_tolerates_unreadable_meta_file(tmp_path):
    (tmp_path / "good.md").write_text("# Good\n")
    (tmp_path / "good.meta.yaml").write_bytes(b"\xff\xfe\x00\x01not-utf8")
    s = store()
    assert await s.seed_dir(str(tmp_path)) == 1
    doc = await s.get("good")
    assert doc["content"] == "# Good\n"
    assert doc["description"] == ""


async def test_seed_dir_skips_unreadable_file(tmp_path):
    (tmp_path / "bad.txt").write_bytes(b"\xff\xfe\x00\x01not-utf8")
    (tmp_path / "good.txt").write_text("hello")
    s = store()
    assert await s.seed_dir(str(tmp_path)) == 1
    assert await s.get("bad") is None
    assert (await s.get("good"))["content"] == "hello"


async def test_seed_dir_skips_invalid_and_unknown_files(tmp_path):
    (tmp_path / "bad.json").write_text("not json")       # fails validation -> warn+skip
    (tmp_path / ".gitkeep").write_text("")               # no kind suffix -> skip
    (tmp_path / "Upper.md").write_text("bad name")       # fails NAME_RE -> warn+skip
    (tmp_path / "good.txt").write_text("hello")
    s = store()
    assert await s.seed_dir(str(tmp_path)) == 1
    assert await s.get("bad") is None
    assert (await s.get("good"))["content"] == "hello"


# ---------- shared career fixture ----------


def _career_dir(tmp_path):
    root = tmp_path / "career"
    root.mkdir()
    (root / "profile.yaml").write_text(
        "name: Alex Example\nemail: owner@example.com\nheadline: Software engineer\n")
    (root / "skills.yaml").write_text("skills:\n  - {name: Python, years: 5}\n")
    exp = root / "experience"
    exp.mkdir()
    (exp / "acme.yaml").write_text(
        "company: Acme Corp\ntitle: Senior Engineer\nstart: 2022-01\nend: present\n"
        "facts:\n"
        "  - id: cut-latency\n"
        '    text: "Cut checkout p99 latency 40%"\n'
        "    skills: [python]\n")
    # full ISO dates: yaml resolves these to datetime.date, which the bank
    # must canonicalize to strings so the seeded json round-trips exactly
    (exp / "beta.yaml").write_text(
        "company: Beta Inc\ntitle: Engineer\nstart: 2020-03-01\nend: 2021-12-31\n"
        "facts:\n"
        "  - id: shipped-widget\n"
        "    text: Shipped the widget\n"
        "    skills: [python]\n")
    return str(root)


# ---------- make_bank_provider ----------


def _bank_data(name="Someone"):
    return {"profile": {"name": name, "email": "a@b.com"}, "skills": [],
            "experiences": [{"company": "Acme", "title": "Eng", "facts": [
                {"id": "a-fact", "text": "did a thing", "skills": ["python"]}]}]}


def _settings_no_career(tmp_path):
    return Settings(_env_file=None, owner_email="me@example.com", session_secret="s3",
                    career_dir=str(tmp_path / "does-not-exist"))


async def test_bank_provider_parses_resource_and_caches(tmp_path):
    settings = _settings_no_career(tmp_path)
    s = store(settings=settings)
    await s.save("career-bank", "json", "", json.dumps(_bank_data()), source="seed")
    provider = make_bank_provider(s, settings)
    bank1 = await provider()
    assert bank1.profile["name"] == "Someone"
    assert bank1.fact_ids == {"a-fact"}
    bank2 = await provider()
    assert bank2 is bank1                       # cached on updated_at


async def test_bank_provider_reparses_when_updated_at_changes(tmp_path):
    settings = _settings_no_career(tmp_path)
    s = store(settings=settings)
    await s.save("career-bank", "json", "", json.dumps(_bank_data()), source="seed")
    provider = make_bank_provider(s, settings)
    assert (await provider()).profile["name"] == "Someone"
    await s.save("career-bank", "json", "",
                 json.dumps(_bank_data(name="Someone Else")), source="user")
    assert (await provider()).profile["name"] == "Someone Else"


async def test_bank_provider_falls_back_to_career_dir_when_resource_absent(tmp_path):
    career = _career_dir(tmp_path)
    settings = Settings(_env_file=None, owner_email="me@example.com",
                        session_secret="s3", career_dir=career)
    provider = make_bank_provider(store(settings=settings), settings)
    bank = await provider()
    assert bank is not None
    assert bank.profile["name"] == "Alex Example"


async def test_bank_provider_returns_none_when_nothing_available(tmp_path):
    settings = _settings_no_career(tmp_path)
    provider = make_bank_provider(store(settings=settings), settings)
    assert await provider() is None


async def test_bank_provider_invalid_resource_yields_none_not_fallback(tmp_path):
    career = _career_dir(tmp_path)          # a valid fallback exists...
    settings = Settings(_env_file=None, owner_email="me@example.com",
                        session_secret="s3", career_dir=career)
    s = store(settings=settings)
    # valid json, invalid bank shape (missing profile.name)
    await s.save("career-bank", "json", "", '{"profile": {"email": "a@b.com"}}',
                 source="user")
    provider = make_bank_provider(s, settings)
    assert await provider() is None         # ...but the broken resource wins

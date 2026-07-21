import asyncio
import json

import pytest

from switchgear.cli import import_json
from switchgear.storage.memory import MemoryStorage
from switchgear.storage.sqlite import SQLiteStorage


@pytest.fixture(params=["memory", "sqlite"])
def storage(request, tmp_path):
    if request.param == "memory":
        return MemoryStorage()
    return SQLiteStorage(tmp_path / "switchgear.sqlite3")


async def test_storage_contract(storage):
    assert await storage.get("things", "one") is None
    await storage.put("things", "one", {"kind": "a", "value": 1})
    await storage.put("things", "two", {"kind": "b", "value": 2})
    assert await storage.get("things", "one") == {"kind": "a", "value": 1}
    assert await storage.query("things", {"kind": "b"}) == [
        {"kind": "b", "value": 2, "_id": "two"}
    ]
    assert await storage.compare_and_set(
        "things", "one", {"value": 1}, {"value": 3}
    ) == {"kind": "a", "value": 3}
    assert await storage.compare_and_set(
        "things", "one", {"value": 1}, {"value": 4}
    ) is None
    await storage.delete("things", "one")
    assert await storage.get("things", "one") is None


async def test_sqlite_persists_across_instances(tmp_path):
    path = tmp_path / "switchgear.sqlite3"
    await SQLiteStorage(path).put("c", "k", {"value": "durable"})
    assert await SQLiteStorage(path).get("c", "k") == {"value": "durable"}


async def test_sqlite_compare_and_set_has_one_winner(tmp_path):
    storage = SQLiteStorage(tmp_path / "switchgear.sqlite3")
    await storage.put("claims", "one", {"status": "open"})
    results = await asyncio.gather(*[
        storage.compare_and_set("claims", "one", {"status": "open"},
                                {"status": f"won-{index}"})
        for index in range(8)
    ])
    assert sum(result is not None for result in results) == 1


async def test_import_legacy_json(tmp_path):
    source = tmp_path / "storage.json"
    source.write_text(json.dumps({"runs": {"r1": {"ok": True}}}))
    database = tmp_path / "switchgear.sqlite3"
    assert await import_json(source, database) == 1
    assert await SQLiteStorage(database).get("runs", "r1") == {"ok": True}

from switchgear.storage.memory import MemoryStorage


async def test_put_get_delete():
    s = MemoryStorage()
    await s.put("jobs", "j1", {"title": "SWE"})
    assert (await s.get("jobs", "j1"))["title"] == "SWE"
    await s.delete("jobs", "j1")
    assert await s.get("jobs", "j1") is None


async def test_query_where_and_limit():
    s = MemoryStorage()
    for i in range(5):
        await s.put("jobs", f"j{i}", {"score": 80 if i < 2 else 40})
    hits = await s.query("jobs", where={"score": 80})
    assert {h["_id"] for h in hits} == {"j0", "j1"}
    assert len(await s.query("jobs", limit=3)) == 3


async def test_json_persistence(tmp_path):
    p = str(tmp_path / "state.json")
    s1 = MemoryStorage(path=p)
    await s1.put("notes", "n1", {"text": "hi"})
    s2 = MemoryStorage(path=p)
    assert (await s2.get("notes", "n1"))["text"] == "hi"


async def test_documents_are_isolated_copies():
    s = MemoryStorage()
    original = {"tags": ["x"]}
    await s.put("jobs", "j1", original)
    original["tags"].append("mutated-after-put")
    fetched = await s.get("jobs", "j1")
    fetched["tags"].append("mutated-after-get")
    assert (await s.get("jobs", "j1"))["tags"] == ["x"]

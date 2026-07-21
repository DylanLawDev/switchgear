import httpx

from switchgear.auth import sign_session
from switchgear.config import Settings
from switchgear.memory.embeddings import FakeEmbedder
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from tests.fakes import FakeGateway

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")


def make_app():
    return create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())


def client(app, authed=True):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    if authed:
        c.cookies.set("session", sign_session(S, "me@example.com"))
    return c


async def create_memory(c, text="prefers tabs", type="episodic", importance=6):
    r = await c.post("/api/memories", json={"text": text, "type": type,
                                            "importance": importance})
    assert r.status_code == 200
    return r.json()


# ---------- wiring ----------


async def test_app_wires_embedder_memory_store_and_tools():
    app = make_app()
    state = app.state.switchgear
    assert isinstance(state.embedder, FakeEmbedder)  # embedding_backend default "fake"
    assert state.memory_store is not None
    assert "save_memory" in state.registry._tools
    assert "search_memory" in state.registry._tools


# ---------- auth (spec §7 invariant 5) ----------


async def test_all_memory_routes_require_owner_auth():
    app = make_app()
    async with client(app, authed=False) as c:
        assert (await c.get("/memories")).status_code == 401
        assert (await c.get("/api/memories")).status_code == 401
        assert (await c.post("/api/memories", json={"text": "x", "type": "core",
                                                    "importance": 5})).status_code == 401
        assert (await c.put("/api/memories/mem-x", json={"text": "x"})).status_code == 401
        assert (await c.post("/api/memories/mem-x/archive")).status_code == 401
        assert (await c.post("/api/memories/mem-x/restore")).status_code == 401
        assert (await c.delete("/api/memories/mem-x")).status_code == 401


async def test_memories_page_renders_with_tab():
    app = make_app()
    async with client(app) as c:
        r = await c.get("/memories")
    assert r.status_code == 200
    assert "Memories" in r.text
    assert "/static/memories.js" in r.text
    assert 'data-tab="memories"' in r.text


# ---------- CRUD ----------


async def test_create_returns_doc_without_embedding():
    app = make_app()
    async with client(app) as c:
        doc = await create_memory(c)
    assert doc["key"].startswith("mem-")
    assert doc["status"] == "active"
    assert doc["source"] == "owner"
    assert "embedding" not in doc


async def test_create_validation_errors_are_400_with_message():
    app = make_app()
    async with client(app) as c:
        r = await c.post("/api/memories", json={"text": "  ", "type": "episodic",
                                                "importance": 5})
        assert r.status_code == 400
        assert "non-empty" in r.json()["detail"]
        r = await c.post("/api/memories", json={"text": "x", "type": "bogus",
                                                "importance": 5})
        assert r.status_code == 400


async def test_list_and_filters():
    app = make_app()
    async with client(app) as c:
        core = await create_memory(c, text="core rule", type="core")
        epi = await create_memory(c, text="a fact", type="episodic")
        await c.post(f"/api/memories/{epi['key']}/archive")
        all_rows = (await c.get("/api/memories")).json()
        assert {r["key"] for r in all_rows} == {core["key"], epi["key"]}
        assert all("embedding" not in r for r in all_rows)
        core_rows = (await c.get("/api/memories", params={"type": "core"})).json()
        assert [r["key"] for r in core_rows] == [core["key"]]
        archived = (await c.get("/api/memories",
                                params={"status": "archived"})).json()
        assert [r["key"] for r in archived] == [epi["key"]]


async def test_update_text_roundtrip_400_and_404():
    app = make_app()
    async with client(app) as c:
        doc = await create_memory(c)
        r = await c.put(f"/api/memories/{doc['key']}", json={"text": "prefers spaces"})
        assert r.status_code == 200
        assert r.json()["text"] == "prefers spaces"
        assert (await c.put("/api/memories/mem-missing",
                            json={"text": "x"})).status_code == 404
        assert (await c.put(f"/api/memories/{doc['key']}",
                            json={"text": ""})).status_code == 400


async def test_archive_restore_flow_and_404():
    app = make_app()
    async with client(app) as c:
        doc = await create_memory(c)
        r = await c.post(f"/api/memories/{doc['key']}/archive")
        assert r.status_code == 200 and r.json()["status"] == "archived"
        r = await c.post(f"/api/memories/{doc['key']}/restore")
        assert r.status_code == 200 and r.json()["status"] == "active"
        assert (await c.post("/api/memories/mem-missing/archive")).status_code == 404
        assert (await c.post("/api/memories/mem-missing/restore")).status_code == 404


async def test_delete_and_404():
    app = make_app()
    async with client(app) as c:
        doc = await create_memory(c)
        assert (await c.delete(f"/api/memories/{doc['key']}")).json() == {"ok": True}
        assert (await c.delete(f"/api/memories/{doc['key']}")).status_code == 404


async def test_writes_are_audited():
    app = make_app()
    async with client(app) as c:
        doc = await create_memory(c)
        await c.put(f"/api/memories/{doc['key']}", json={"text": "edited"})
        await c.post(f"/api/memories/{doc['key']}/archive")
        await c.delete(f"/api/memories/{doc['key']}")
    audit = await app.state.switchgear.storage.query("audit")
    assert sorted(a["action"] for a in audit) == [
        "memory_archive", "memory_delete", "memory_save", "memory_update_text"]

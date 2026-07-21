import httpx

from switchgear.auth import sign_session
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from tests.fakes import FakeGateway

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")

DOC = {"kind": "md", "description": "team notes", "content": "# Notes\nhello"}


def make_app():
    return create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())


def client(app):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    return c


async def test_api_requires_auth():
    app = make_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        assert (await c.get("/api/resources")).status_code == 401
        assert (await c.get("/api/resources/notes")).status_code == 401
        assert (await c.put("/api/resources/notes", json=DOC)).status_code == 401
        assert (await c.delete("/api/resources/notes")).status_code == 401


async def test_page_requires_auth_and_redirects_browsers():
    app = make_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        r = await c.get("/resources", headers={"accept": "text/html"},
                        follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/login"


async def test_crud_roundtrip():
    app = make_app()
    async with client(app) as c:
        r = await c.put("/api/resources/notes", json=DOC)
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "notes"
        assert body["kind"] == "md"
        assert body["source"] == "user"
        assert body["size"] == len(DOC["content"].encode())

        rows = (await c.get("/api/resources")).json()
        assert [row["name"] for row in rows] == ["notes"]
        assert "content" not in rows[0]

        one = (await c.get("/api/resources/notes")).json()
        assert one["content"] == DOC["content"]

        r = await c.put("/api/resources/notes", json={**DOC, "content": "# v2"})
        assert r.json()["content"] == "# v2"

        assert (await c.delete("/api/resources/notes")).json() == {"ok": True}
        assert (await c.get("/api/resources/notes")).status_code == 404
        assert (await c.delete("/api/resources/notes")).status_code == 404


async def test_put_invalid_returns_400_with_message():
    app = make_app()
    async with client(app) as c:
        r = await c.put("/api/resources/data",
                        json={"kind": "json", "description": "", "content": "not json"})
        assert r.status_code == 400
        assert "not valid json" in r.json()["detail"]

        r = await c.put("/api/resources/BADNAME", json=DOC)
        assert r.status_code == 400
        assert "invalid name" in r.json()["detail"]

        r = await c.put("/api/resources/data",
                        json={"kind": "exe", "description": "", "content": "x"})
        assert r.status_code == 400
        assert "unknown kind" in r.json()["detail"]


async def test_put_kind_immutable_returns_400():
    app = make_app()
    async with client(app) as c:
        await c.put("/api/resources/notes", json=DOC)
        r = await c.put("/api/resources/notes",
                        json={"kind": "txt", "description": "", "content": "plain"})
        assert r.status_code == 400
        assert "immutable" in r.json()["detail"]


async def test_editing_seed_resource_flips_source_to_user():
    app = make_app()
    await app.state.switchgear.resource_store.save(
        "notes", "md", "seeded", "v1", source="seed")
    async with client(app) as c:
        r = await c.put("/api/resources/notes",
                        json={"kind": "md", "description": "seeded", "content": "v2"})
    assert r.json()["source"] == "user"
    doc = await app.state.switchgear.resource_store.get("notes")
    assert doc["source"] == "user"
    assert doc["content"] == "v2"


async def test_writes_are_audited():
    app = make_app()
    async with client(app) as c:
        await c.put("/api/resources/notes", json=DOC)
        await c.delete("/api/resources/notes")
    audit = await app.state.switchgear.storage.query("audit")
    actions = [a["action"] for a in audit]
    assert "resource_save" in actions
    assert "resource_delete" in actions


async def test_lifespan_seeds_resources_dir_but_not_career_bank(tmp_path):
    # spec §3.6: no preloaded career data on first boot — resources/ seeding
    # is unaffected, but career-bank must never be auto-seeded from career/.
    seed_dir = tmp_path / "resources"
    seed_dir.mkdir()
    (seed_dir / "handbook.md").write_text("# Handbook\n")
    s = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3",
                 resources_dir=str(seed_dir), career_dir="career")
    app = create_app(settings=s, gateway=FakeGateway([]), storage=MemoryStorage())
    async with app.router.lifespan_context(app):
        store = app.state.switchgear.resource_store
        handbook = await store.get("handbook")
        career = await store.get("career-bank")
    assert handbook is not None and handbook["source"] == "seed"
    assert career is None


async def test_resources_page_renders_shell():
    app = make_app()
    async with client(app) as c:
        r = await c.get("/resources")
    assert r.status_code == 200
    assert "resources.js" in r.text
    assert 'class="tab active" data-tab="resources"' in r.text


async def test_settings_roundtrip_and_validation():
    app = make_app()
    async with client(app) as c:
        assert (await c.get("/api/resources/settings")).json() == {
            "write_mode": "prompt"}
        r = await c.put("/api/resources/settings", json={"write_mode": "full"})
        assert r.json() == {"write_mode": "full"}
        r = await c.put("/api/resources/settings", json={"write_mode": "nope"})
        assert r.status_code == 400


async def test_pending_lifecycle_via_api():
    app = make_app()
    svc = app.state.switchgear.resource_writes
    async with client(app) as c:
        await svc.propose("create", "notes", kind="md", content="# hi")
        [p] = (await c.get("/api/resources/pending")).json()
        assert p["resource_name"] == "notes" and p["status"] == "pending"
        r = await c.post(f"/api/resources/pending/{p['id']}/approve")
        assert r.json() == {"ok": True}
        assert (await c.get("/api/resources/notes")).json()["source"] == "agent"
        assert (await c.get("/api/resources/pending")).json() == []
        assert (await c.post("/api/resources/pending/nope/approve")).status_code == 404


async def test_owner_put_auto_rejects_pending():
    app = make_app()
    svc = app.state.switchgear.resource_writes
    async with client(app) as c:
        await c.put("/api/resources/notes", json=DOC)
        await svc.propose("update", "notes", content="# agent version")
        await c.put("/api/resources/notes", json={**DOC, "content": "# owner"})
        assert (await c.get("/api/resources/pending")).json() == []


async def test_pending_endpoints_require_auth():
    app = make_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        assert (await c.get("/api/resources/settings")).status_code == 401
        assert (await c.get("/api/resources/pending")).status_code == 401
        assert (await c.post("/api/resources/pending/x/approve")).status_code == 401

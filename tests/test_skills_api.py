import httpx

from switchgear.auth import sign_session
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from tests.fakes import FakeGateway

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")

PENDING = """---
name: draft-skill
description: A drafted skill
tools: [http_fetch]
---
Do the drafted thing.
"""


def client(app):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    return c


async def test_skills_api_requires_auth():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        assert (await c.get("/api/skills")).status_code == 401


async def test_list_get_and_approve_flow():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    await app.state.switchgear.skill_store.save(PENDING, source="agent")
    async with client(app) as c:
        listed = (await c.get("/api/skills")).json()
        assert listed[0]["name"] == "draft-skill" and listed[0]["status"] == "pending"
        assert (await c.get("/api/skills/draft-skill")).json()["body"].strip() \
            == "Do the drafted thing."
        assert (await c.get("/api/skills/ghost")).status_code == 404
        r = await c.post("/api/skills/draft-skill/approve")
        assert r.status_code == 200 and r.json()["status"] == "active"
    audit = await app.state.switchgear.storage.query("audit")
    assert any(a.get("action") == "skill_approve" for a in audit)


async def test_approve_missing_is_404():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with client(app) as c:
        assert (await c.post("/api/skills/ghost/approve")).status_code == 404


async def test_put_rejects_mismatched_name_without_saving_other_skill():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    other = PENDING.replace("draft-skill", "other-skill")
    async with client(app) as c:
        response = await c.put("/api/skills/draft-skill", json={"text": other})
    assert response.status_code == 400
    assert await app.state.switchgear.skill_store.get("other-skill") is None


async def test_manual_run_and_run_history():
    gw = FakeGateway([[{"type": "text", "delta": "done"},
                       {"type": "message", "usage": 4,
                        "message": {"role": "assistant", "content": "done"}}]])
    app = create_app(settings=S, gateway=gw, storage=MemoryStorage())
    await app.state.switchgear.skill_store.save(PENDING, source="repo")  # active
    async with client(app) as c:
        run = (await c.post("/api/skills/draft-skill/run")).json()
        assert run["ok"] is True
        runs = (await c.get("/api/skills/draft-skill/runs")).json()
    assert len(runs) == 1 and runs[0]["trigger"] == "manual"


async def test_seed_dir_loads_system_skill():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    seeded = await app.state.switchgear.skill_store.seed_dir("skills")
    assert seeded >= 1
    assert (await app.state.switchgear.skill_store.get("author-skills"))["status"] == "active"

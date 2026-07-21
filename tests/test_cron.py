import httpx

from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from tests.fakes import FakeGateway

SKILL = """---
name: brief
description: Daily brief
tools: [storage]
---
Report done.
"""


def done():
    return [[{"type": "text", "delta": "ok"},
             {"type": "message", "usage": 2,
              "message": {"role": "assistant", "content": "ok"}}]]


async def seed_active(app):
    await app.state.switchgear.skill_store.save(SKILL, source="repo")


async def test_secret_header_runs_skill():
    s = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3",
                 cron_secret="topsecret")
    app = create_app(settings=s, gateway=FakeGateway(done()), storage=MemoryStorage())
    await seed_active(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        r = await c.post("/tasks/run-skill/brief", headers={"X-Cron-Secret": "topsecret"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert len(await app.state.switchgear.storage.query("runs")) == 1


async def test_no_credential_is_401():
    s = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3",
                 cron_secret="topsecret")
    app = create_app(settings=s, gateway=FakeGateway([]), storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        r = await c.post("/tasks/run-skill/brief")
    assert r.status_code == 401

async def test_wrong_secret_is_401():
    s = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3",
                 cron_secret="topsecret")
    app = create_app(settings=s, gateway=FakeGateway([]), storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        r = await c.post("/tasks/run-skill/brief", headers={"X-Cron-Secret": "nope"})
    assert r.status_code == 401

import httpx

from switchgear.auth import sign_session
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from switchgear.web.settings_routes import USER_SETTING_NAMES
from tests.fakes import FakeGateway


OWNER = "owner@example.com"


def make_app(storage=None):
    settings = Settings(_env_file=None, owner_email=OWNER, session_secret="s3")
    return create_app(settings=settings, storage=storage or MemoryStorage(),
                      gateway=FakeGateway([]))


def client(app):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(app.state.switchgear.settings, OWNER))
    return c


async def test_settings_get_exposes_safe_user_fields_only():
    app = make_app()
    async with client(app) as c:
        response = await c.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["owner_email"] == OWNER
    assert body["model_chat"] == app.state.switchgear.settings.model_chat
    assert "gateway_api_key" not in body
    assert "session_secret" not in body


async def test_settings_put_persists_and_applies_immediately():
    storage = MemoryStorage()
    app = make_app(storage)
    async with client(app) as c:
        current = (await c.get("/api/settings")).json()
        current.pop("owner_email")
        current.update({"model_chat": "new/chat", "memory_recall_k": 9})
        response = await c.put("/api/settings", json=current)
    assert response.status_code == 200
    assert app.state.switchgear.settings.model_chat == "new/chat"
    assert app.state.switchgear.settings.memory_recall_k == 9
    stored = await storage.get("app-settings", "user")
    assert stored["model_chat"] == "new/chat"
    assert "owner_email" not in stored


async def test_settings_put_validates_bounds():
    app = make_app()
    async with client(app) as c:
        body = (await c.get("/api/settings")).json()
        body.pop("owner_email")
        body["memory_recall_floor"] = 2
        response = await c.put("/api/settings", json=body)
    assert response.status_code == 422


async def test_lifespan_loads_persisted_overrides():
    storage = MemoryStorage()
    app = make_app(storage)
    values = {name: getattr(app.state.switchgear.settings, name)
              for name in USER_SETTING_NAMES}
    values["model_bulk"] = "persisted/bulk"
    await storage.put("app-settings", "user", values)
    async with app.router.lifespan_context(app):
        assert app.state.switchgear.settings.model_bulk == "persisted/bulk"


async def test_logout_expires_session_cookie():
    app = make_app()
    async with client(app) as c:
        response = await c.post("/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    cookie = response.headers["set-cookie"]
    assert "session=" in cookie and "Max-Age=0" in cookie

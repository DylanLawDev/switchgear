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
        current = {k: v for k, v in current.items()
                   if k not in {"owner_email", "gateway_api_key_set", "smtp_password_set"}}
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


async def test_settings_includes_gateway_and_email_fields():
    app = make_app()
    async with client(app) as c:
        body = (await c.get("/api/settings")).json()
    assert body["gateway_base_url"].startswith("https://")
    assert body["email_backend"] == "console"
    assert body["owner_timezone"] == "Etc/UTC"
    assert body["smtp_port"] == 587


async def test_settings_put_smtp_requires_host_and_from():
    app = make_app()
    async with client(app) as c:
        current = (await c.get("/api/settings")).json()
        current = {k: v for k, v in current.items()
                   if k not in {"owner_email", "gateway_api_key_set", "smtp_password_set"}}
        current.update({"email_backend": "smtp", "smtp_host": "", "smtp_from": ""})
        response = await c.put("/api/settings", json=current)
    assert response.status_code == 422


async def test_settings_put_rejects_unknown_timezone():
    app = make_app()
    async with client(app) as c:
        current = (await c.get("/api/settings")).json()
        current = {k: v for k, v in current.items()
                   if k not in {"owner_email", "gateway_api_key_set", "smtp_password_set"}}
        current["owner_timezone"] = "Mars/Olympus"
        response = await c.put("/api/settings", json=current)
    assert response.status_code == 422


async def test_settings_put_applies_gateway_base_url():
    storage = MemoryStorage()
    app = make_app(storage)
    async with client(app) as c:
        current = (await c.get("/api/settings")).json()
        current = {k: v for k, v in current.items()
                   if k not in {"owner_email", "gateway_api_key_set", "smtp_password_set"}}
        current["gateway_base_url"] = "https://gw.example/v1"
        response = await c.put("/api/settings", json=current)
    assert response.status_code == 200
    assert app.state.switchgear.settings.gateway_base_url == "https://gw.example/v1"
    assert (await storage.get("app-settings", "user"))["gateway_base_url"] \
        == "https://gw.example/v1"


async def test_secrets_are_write_only_and_presence_reported():
    storage = MemoryStorage()
    app = make_app(storage)
    async with client(app) as c:
        body = (await c.get("/api/settings")).json()
        assert body["gateway_api_key_set"] is False
        payload = {k: v for k, v in body.items()
                   if k not in {"owner_email", "gateway_api_key_set", "smtp_password_set"}}
        payload["gateway_api_key"] = "sk-secret-123"
        response = await c.put("/api/settings", json=payload)
        assert response.status_code == 200
        assert response.json()["gateway_api_key_set"] is True
        assert "gateway_api_key" not in response.json()
        body2 = (await c.get("/api/settings")).json()
    assert body2["gateway_api_key_set"] is True
    assert "gateway_api_key" not in body2
    assert app.state.switchgear.settings.gateway_api_key == "sk-secret-123"
    assert (await storage.get("app-settings", "secure"))["gateway_api_key"] == "sk-secret-123"


async def test_put_with_empty_secret_keeps_existing():
    storage = MemoryStorage()
    app = make_app(storage)
    async with client(app) as c:
        body = (await c.get("/api/settings")).json()
        payload = {k: v for k, v in body.items()
                   if k not in {"owner_email", "gateway_api_key_set", "smtp_password_set"}}
        payload["gateway_api_key"] = "sk-first"
        await c.put("/api/settings", json=payload)
        payload["gateway_api_key"] = ""
        await c.put("/api/settings", json=payload)
    assert app.state.switchgear.settings.gateway_api_key == "sk-first"


async def test_secure_overrides_loaded_from_storage():
    from switchgear.web.settings_routes import load_secure_overrides

    storage = MemoryStorage()
    await storage.put("app-settings", "secure",
                      {"gateway_api_key": "sk-db", "smtp_password": "",
                       "local_password_hash": "scrypt:x", "owner_email": "db@x.y"})
    app = make_app(storage)
    state = app.state.switchgear
    state.settings.smtp_password = "env-value"
    await load_secure_overrides(state)
    assert state.settings.gateway_api_key == "sk-db"
    assert state.settings.smtp_password == "env-value"  # empty DB value skipped
    assert state.settings.local_password_hash == "scrypt:x"
    assert state.settings.owner_email == "db@x.y"


import respx


@respx.mock
async def test_gateway_test_success_counts_models():
    respx.get("https://gw.test/v1/models").respond(
        json={"data": [{"id": "a"}, {"id": "b"}]})
    app = make_app()
    async with client(app) as c:
        response = await c.post("/api/settings/test-gateway",
                                json={"gateway_base_url": "https://gw.test/v1",
                                      "gateway_api_key": "sk-x"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "models": 2}
    assert respx.calls.last.request.headers["authorization"] == "Bearer sk-x"


@respx.mock
async def test_gateway_test_reports_auth_failure():
    respx.get("https://gw.test/v1/models").respond(status_code=401)
    app = make_app()
    async with client(app) as c:
        response = await c.post("/api/settings/test-gateway",
                                json={"gateway_base_url": "https://gw.test/v1",
                                      "gateway_api_key": "bad"})
    assert response.json() == {"ok": False, "detail": "gateway returned 401"}


@respx.mock
async def test_gateway_test_falls_back_to_effective_settings():
    respx.get("https://fallback.test/v1/models").respond(json={"data": []})
    app = make_app()
    app.state.switchgear.settings.gateway_base_url = "https://fallback.test/v1"
    app.state.switchgear.settings.gateway_api_key = "sk-saved"
    async with client(app) as c:
        response = await c.post("/api/settings/test-gateway", json={})
    assert response.json()["ok"] is True
    assert respx.calls.last.request.headers["authorization"] == "Bearer sk-saved"


@respx.mock
async def test_gateway_test_reports_connection_error():
    import httpx as _httpx
    respx.get("https://down.test/v1/models").mock(
        side_effect=_httpx.ConnectError("boom"))
    app = make_app()
    async with client(app) as c:
        response = await c.post("/api/settings/test-gateway",
                                json={"gateway_base_url": "https://down.test/v1",
                                      "gateway_api_key": "k"})
    assert response.json() == {"ok": False, "detail": "connection failed: ConnectError"}

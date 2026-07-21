import httpx
import pytest

from switchgear.auth import sign_session
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from switchgear.web import spa
from tests.fakes import FakeGateway

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")


def client(app):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    return c


@pytest.fixture
def fake_spa(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "index.html").write_text("<html>SPA</html>")
    monkeypatch.setattr(spa, "STATIC_DIR", tmp_path)
    return app_dir


async def test_legacy_workflow_url_redirects():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with client(app) as c:
        r = await c.get("/w/job-hunt", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "/workflows/job-hunt"


async def test_workflows_routes_without_spa():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with client(app) as c:
        # no workflows seeded in this app → index falls through to /
        r = await c.get("/workflows", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == "/"
        assert (await c.get("/workflows/ghost")).status_code == 404


async def test_spa_serves_app_routes(fake_spa):
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with client(app) as c:
        for path in ("/", "/skills", "/workflows", "/workflows/anything",
                     "/resources", "/memories", "/channels", "/settings"):
            r = await c.get(path)
            assert r.status_code == 200, path
            assert "SPA" in r.text, path
            assert r.headers["cache-control"] == "no-cache"
        r = await c.get("/channels/email", follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"] == "/channels"


async def test_spa_routes_still_require_auth(fake_spa):
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        for path in ("/workflows", "/channels", "/"):
            assert (await c.get(path)).status_code == 401, path

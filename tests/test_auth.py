import httpx
from fastapi import Depends, FastAPI

from switchgear.auth import (
    hash_password,
    login_csrf,
    require_owner,
    router,
    sign_session,
    verify_password,
)
from switchgear.config import Settings, get_settings

S = Settings(_env_file=None, owner_email="owner@example.com", session_secret="s3")


def make_app(settings: Settings = S):
    app = FastAPI()
    app.include_router(router)

    async def settings_override():
        return settings

    app.dependency_overrides[get_settings] = settings_override

    @app.get("/private")
    async def private(email: str = Depends(require_owner)):
        return {"email": email}

    return app


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_require_owner_guards():
    async with client(make_app()) as c:
        assert (await c.get("/private")).status_code == 401
        c.cookies.set("session", sign_session(S, "owner@example.com"))
        response = await c.get("/private")
    assert response.status_code == 200
    assert response.json()["email"] == "owner@example.com"


async def test_require_owner_rejects_tampered_and_non_owner_cookies():
    async with client(make_app()) as c:
        c.cookies.set("session", "garbage.tampered")
        assert (await c.get("/private")).status_code == 401
    async with client(make_app()) as c:
        c.cookies.set("session", sign_session(S, "other@example.com"))
        assert (await c.get("/private")).status_code == 401


def test_local_password_hash_round_trip():
    encoded = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)


async def test_local_login_requires_csrf_and_sets_session():
    settings = Settings(
        _env_file=None, owner_email="owner@example.com",
        local_password_hash=hash_password("secret"), session_secret="session",
        cookie_secure=False,
    )
    async with client(make_app(settings)) as c:
        assert (await c.post("/auth/local", content="password=secret")).status_code == 403
        csrf = login_csrf(settings)
        c.cookies.set("login_csrf", csrf)
        response = await c.post(
            "/auth/local", content=f"csrf={csrf}&password=secret",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert response.status_code == 303
    assert "session=" in response.headers["set-cookie"]


def test_hash_password_round_trips_with_verify():
    from switchgear.auth import hash_password as auth_hash_password

    encoded = auth_hash_password("hunter22")
    assert encoded.startswith("scrypt:16384:8:1:")
    assert verify_password("hunter22", encoded)
    assert not verify_password("wrong", encoded)

# Unified Setup and Gateway Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One deployment story everywhere — a thin local setup script plus a token-gated browser first-run wizard, with gateway/email/timezone/password configurable at runtime from the Settings UI, layered as database → env → default.

**Architecture:** Extends the existing `app-settings` storage-override pattern (`load_settings_overrides` + live `setattr` on the shared `Settings` object). A new `secure` document holds secrets (write-only through the API); a new `setup-token` document gates the one-time claim flow. `create_app` no longer requires auth env vars; an unclaimed instance serves a `/setup` wizard.

**Tech Stack:** FastAPI + pydantic v2, httpx/respx, pytest (async, no decorators needed — asyncio_mode is auto), React + TanStack Query + vitest/msw, bash.

**Spec:** `docs/superpowers/specs/2026-07-23-unified-setup-and-gateway-config-design.md`

## Global Constraints

- Secrets (`gateway_api_key`, `smtp_password`, `local_password_hash`, `session_secret`) are NEVER returned by any endpoint; presence booleans only.
- Precedence everywhere: database value → environment variable → default. Empty-string DB values never override env.
- Setup token comparison uses `hmac.compare_digest`; failure sleeps ~0.5 s.
- Password minimum length 8.
- Log line format for the token (scripts grep for `SETUP required`): `SETUP required — visit {public_base_url}/setup  token: {token}`
- All new endpoints return JSON; test-gateway failures are HTTP 200 with `{"ok": false}`.
- Python: run tests with `UV_CACHE_DIR=/tmp/uv-cache uv run pytest`; lint with `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src tests`. Frontend: `cd frontend && npm test -- --run`.
- Follow existing code style: 4-space Python, ~100-col lines, minimal comments.

---

### Task 1: Move `hash_password` into `switchgear.auth`

**Files:**
- Modify: `src/switchgear/auth.py` (add function after `verify_password`, add `os` import)
- Modify: `src/switchgear/cli.py` (import from auth, delete local copy)
- Test: `tests/test_auth.py` (append)

**Interfaces:**
- Produces: `switchgear.auth.hash_password(password: str) -> str` — scrypt hash in the exact format `verify_password` parses. Later tasks (claim endpoint, password change) call this.

- [ ] **Step 1: Write the failing test** — append to `tests/test_auth.py`:

```python
def test_hash_password_round_trips_with_verify():
    from switchgear.auth import hash_password, verify_password

    encoded = hash_password("hunter22")
    assert encoded.startswith("scrypt:16384:8:1:")
    assert verify_password("hunter22", encoded)
    assert not verify_password("wrong", encoded)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_auth.py::test_hash_password_round_trips_with_verify -v`
Expected: FAIL — `ImportError: cannot import name 'hash_password'`

- [ ] **Step 3: Implement** — in `src/switchgear/auth.py`, add `import os` to the imports and this function directly after `verify_password`:

```python
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt:16384:8:1:" + base64.urlsafe_b64encode(salt).decode() + ":" + \
        base64.urlsafe_b64encode(digest).decode()
```

In `src/switchgear/cli.py`: delete the local `hash_password` function and the now-unused `base64`, `hashlib`, `os` imports; add `from switchgear.auth import hash_password`.

- [ ] **Step 4: Run tests**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_auth.py tests/test_cli.py -v` (skip `test_cli.py` if it does not exist)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/auth.py src/switchgear/cli.py tests/test_auth.py
git commit -m "Move hash_password into auth module"
```

---

### Task 2: Config — `setup_token` field, shared dev-secret constant, relaxed boot validation

**Files:**
- Modify: `src/switchgear/config.py`
- Modify: `src/switchgear/web/app.py` (import `DEV_SESSION_SECRET` from config, delete local constant)
- Test: `tests/test_config.py` (append)

**Interfaces:**
- Produces: `Settings.setup_token: str` (env `SWITCHGEAR_SETUP_TOKEN`); `switchgear.config.DEV_SESSION_SECRET`; `validate_runtime()` that no longer raises for missing `local_password_hash`/`owner_email`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_config.py`:

```python
def test_validate_runtime_allows_unclaimed_boot():
    s = Settings(_env_file=None)  # no password hash, no owner email
    s.validate_runtime()  # must not raise


def test_setup_token_reads_env(monkeypatch):
    monkeypatch.setenv("SWITCHGEAR_SETUP_TOKEN", "preset-token")
    assert Settings(_env_file=None).setup_token == "preset-token"
```

Note: `test_validate_runtime_allows_unclaimed_boot` also exercises the dev-session-secret path — `Settings(_env_file=None)` keeps the dev default with a localhost `public_base_url`, which must stay allowed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_config.py -v`
Expected: the two new tests FAIL (RuntimeError about password hash; AttributeError for setup_token)

- [ ] **Step 3: Implement** — in `src/switchgear/config.py`:

Add near the top (after imports):

```python
DEV_SESSION_SECRET = "dev-secret-change-me"
```

Add the field to `Settings` (next to `cron_secret`):

```python
    setup_token: str = ""
```

In `validate_runtime`, replace the hard-coded `"dev-secret-change-me"` literal with `DEV_SESSION_SECRET` and DELETE these two checks (they become setup-mode, spec "Boot states"):

```python
        if not self.local_password_hash:
            raise RuntimeError("SWITCHGEAR_LOCAL_PASSWORD_HASH is required for local authentication")
        if not self.owner_email:
            raise RuntimeError("SWITCHGEAR_OWNER_EMAIL is required")
```

In `src/switchgear/web/app.py`: delete `DEV_SESSION_SECRET = "dev-secret-change-me"` and add `DEV_SESSION_SECRET` to the existing `from switchgear.config import ...` import.

- [ ] **Step 4: Run tests**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_config.py tests/test_settings_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/config.py src/switchgear/web/app.py tests/test_config.py
git commit -m "Allow unclaimed boot; add setup token setting"
```

---

### Task 3: `DynamicEmailSender` — runtime backend switching

**Files:**
- Modify: `src/switchgear/email/sender.py` (append class)
- Modify: `src/switchgear/email/__init__.py`
- Test: `tests/test_email.py` (append)

**Interfaces:**
- Produces: `get_email_sender(settings)` now returns `DynamicEmailSender`, which delegates per send based on `settings.email_backend` and exposes `.sent` (console log) plus `.console`/`.smtp` attributes.

- [ ] **Step 1: Write the failing test** — append to `tests/test_email.py`:

```python
async def test_dynamic_sender_switches_backend_at_runtime(monkeypatch):
    from switchgear.config import Settings
    from switchgear.email import get_email_sender
    from switchgear.email.sender import DynamicEmailSender

    settings = Settings(_env_file=None, email_backend="console")
    sender = get_email_sender(settings)
    assert isinstance(sender, DynamicEmailSender)
    await sender.send("a@b.c", "hi", "<p>x</p>")
    assert sender.sent[0]["to"] == "a@b.c"

    smtp_calls = []

    async def fake_smtp_send(to, subject, html):
        smtp_calls.append(to)

    monkeypatch.setattr(sender.smtp, "send", fake_smtp_send)
    settings.email_backend = "smtp"
    await sender.send("d@e.f", "yo", "<p>y</p>")
    assert smtp_calls == ["d@e.f"]
    assert len(sender.sent) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_email.py -v`
Expected: new test FAILS — `ImportError: cannot import name 'DynamicEmailSender'`

- [ ] **Step 3: Implement** — append to `src/switchgear/email/sender.py`:

```python
class DynamicEmailSender(EmailSender):
    """Delegates per send so the backend can change at runtime (Settings UI)."""

    def __init__(self, settings: Settings):
        self._s = settings
        self.console = ConsoleEmailSender()
        self.smtp = SMTPEmailSender(settings)

    @property
    def sent(self) -> list[dict]:
        return self.console.sent

    async def send(self, to: str, subject: str, html: str) -> None:
        sender = self.smtp if self._s.email_backend == "smtp" else self.console
        await sender.send(to, subject, html)
```

Replace the body of `src/switchgear/email/__init__.py`:

```python
from switchgear.config import Settings
from switchgear.email.sender import (
    ConsoleEmailSender,
    DynamicEmailSender,
    EmailSender,
    SMTPEmailSender,
)


def get_email_sender(settings: Settings) -> EmailSender:
    return DynamicEmailSender(settings)
```

- [ ] **Step 4: Run the full suite** (other tests may construct senders):

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
Expected: PASS. If a test asserts `isinstance(..., ConsoleEmailSender)` or constructs via `get_email_sender` and pokes internals, update it to use the `.console` attribute or the `.sent` property — do not weaken the assertion.

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/email/ tests/test_email.py
git commit -m "Add runtime-switchable email sender"
```

---

### Task 4: Extend `UserSettings` with gateway/email/timezone non-secret fields

**Files:**
- Modify: `src/switchgear/web/settings_routes.py`
- Test: `tests/test_settings_api.py` (append)

**Interfaces:**
- Produces: `UserSettings` additionally validates `gateway_base_url`, `owner_timezone`, `email_backend`, `smtp_host`, `smtp_port`, `smtp_username`, `smtp_from`, `smtp_starttls`. `GET/PUT /api/settings` round-trips them. Constant `SECURE_KEY = "secure"` exported for later tasks.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_settings_api.py`:

```python
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
        current.pop("owner_email")
        current.update({"email_backend": "smtp", "smtp_host": "", "smtp_from": ""})
        response = await c.put("/api/settings", json=current)
    assert response.status_code == 422


async def test_settings_put_rejects_unknown_timezone():
    app = make_app()
    async with client(app) as c:
        current = (await c.get("/api/settings")).json()
        current.pop("owner_email")
        current["owner_timezone"] = "Mars/Olympus"
        response = await c.put("/api/settings", json=current)
    assert response.status_code == 422


async def test_settings_put_applies_gateway_base_url():
    storage = MemoryStorage()
    app = make_app(storage)
    async with client(app) as c:
        current = (await c.get("/api/settings")).json()
        current.pop("owner_email")
        current["gateway_base_url"] = "https://gw.example/v1"
        response = await c.put("/api/settings", json=current)
    assert response.status_code == 200
    assert app.state.switchgear.settings.gateway_base_url == "https://gw.example/v1"
    assert (await storage.get("app-settings", "user"))["gateway_base_url"] \
        == "https://gw.example/v1"
```

Note: these PUT tests round-trip the GET body, which after Task 5 contains `gateway_api_key_set`/`smtp_password_set` booleans. Strip them in Task 5's update to the PUT model — for now GET does not return them.

- [ ] **Step 2: Run tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_settings_api.py -v`
Expected: new tests FAIL (missing keys / 422 not raised)

- [ ] **Step 3: Implement** — in `src/switchgear/web/settings_routes.py`:

Replace the imports and model header with:

```python
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from switchgear import auth
from switchgear.web.spa import spa_index, spa_response


SETTINGS_COLLECTION = "app-settings"
SETTINGS_KEY = "user"
SECURE_KEY = "secure"
```

Add these fields at the TOP of `UserSettings` (before `model_chat`):

```python
    gateway_base_url: str = Field(min_length=8, max_length=500, pattern=r"^https?://")
    owner_timezone: str = Field(min_length=1, max_length=100)
    email_backend: Literal["console", "smtp"]
    smtp_host: str = Field(max_length=500)
    smtp_port: int = Field(ge=1, le=65535)
    smtp_username: str = Field(max_length=500)
    smtp_from: str = Field(max_length=500)
    smtp_starttls: bool
```

Add validators inside `UserSettings` after the fields:

```python
    @field_validator("owner_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError("unknown timezone") from None
        return value

    @model_validator(mode="after")
    def _smtp_complete(self) -> "UserSettings":
        if self.email_backend == "smtp" and not (self.smtp_host and self.smtp_from):
            raise ValueError("smtp_host and smtp_from are required for the smtp backend")
        return self
```

`USER_SETTING_NAMES`, `current_user_settings`, `load_settings_overrides`, and both routes need no changes — the new fields flow through `tuple(UserSettings.model_fields)` automatically.

- [ ] **Step 4: Run tests**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_settings_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/web/settings_routes.py tests/test_settings_api.py
git commit -m "Expose gateway, email, and timezone settings via API"
```

---

### Task 5: Secure settings — write-only secrets, presence booleans, secure-doc load

**Files:**
- Modify: `src/switchgear/web/settings_routes.py`
- Test: `tests/test_settings_api.py` (append)

**Interfaces:**
- Consumes: `SECURE_KEY` (Task 4).
- Produces: `secret_presence(settings) -> dict` (`gateway_api_key_set`, `smtp_password_set`); `load_secure_overrides(state)`; `PUT /api/settings` accepts optional `gateway_api_key`/`smtp_password` (empty = keep); `GET /api/settings` returns presence booleans, never values.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_settings_api.py`:

```python
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
```

Also update Task 4's PUT-round-trip tests: after this task, GET returns the two booleans, so each existing `current.pop("owner_email")` in `tests/test_settings_api.py` PUT tests must become:

```python
        current = {k: v for k, v in current.items()
                   if k not in {"owner_email", "gateway_api_key_set", "smtp_password_set"}}
```

(Extra keys would 422 against `extra="forbid"`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_settings_api.py -v`
Expected: new tests FAIL (`gateway_api_key_set` KeyError / ImportError)

- [ ] **Step 3: Implement** — in `src/switchgear/web/settings_routes.py`:

After `current_user_settings`, add:

```python
SECURE_SETTING_NAMES = ("gateway_api_key", "smtp_password", "local_password_hash",
                        "owner_email", "session_secret")


def secret_presence(settings) -> dict:
    return {"gateway_api_key_set": bool(settings.gateway_api_key),
            "smtp_password_set": bool(settings.smtp_password)}


async def load_secure_overrides(state) -> None:
    stored = await state.storage.get(SETTINGS_COLLECTION, SECURE_KEY) or {}
    for name in SECURE_SETTING_NAMES:
        value = stored.get(name)
        if value:
            setattr(state.settings, name, value)
```

Add the update model after `UserSettings`:

```python
class UserSettingsUpdate(UserSettings):
    gateway_api_key: str = Field(default="", max_length=500)
    smtp_password: str = Field(default="", max_length=500)
```

Replace both route bodies:

```python
    @app.get("/api/settings")
    async def get_user_settings(email: str = Depends(auth.require_owner)):
        return {**current_user_settings(state.settings), "owner_email": email,
                **secret_presence(state.settings)}

    @app.put("/api/settings")
    async def put_user_settings(body: UserSettingsUpdate,
                                email: str = Depends(auth.require_owner)):
        values = body.model_dump()
        secret_values = {name: values.pop(name)
                        for name in ("gateway_api_key", "smtp_password")}
        await state.storage.put(SETTINGS_COLLECTION, SETTINGS_KEY, values)
        for name, value in values.items():
            setattr(state.settings, name, value)
        updates = {name: value for name, value in secret_values.items() if value}
        if updates:
            stored = await state.storage.get(SETTINGS_COLLECTION, SECURE_KEY) or {}
            stored.update(updates)
            await state.storage.put(SETTINGS_COLLECTION, SECURE_KEY, stored)
            for name, value in updates.items():
                setattr(state.settings, name, value)
        return {**values, "owner_email": email, **secret_presence(state.settings)}
```

IMPORTANT: `USER_SETTING_NAMES = tuple(UserSettings.model_fields)` must remain based on `UserSettings`, NOT `UserSettingsUpdate` — the stored `user` doc stays secret-free.

In `src/switchgear/web/app.py` lifespan, directly after `await load_settings_overrides(state)`:

```python
        from switchgear.web.settings_routes import load_secure_overrides

        await load_secure_overrides(state)
```

(Merge into the existing `from switchgear.web.settings_routes import ...` import line.)

- [ ] **Step 4: Run tests**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_settings_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/web/settings_routes.py src/switchgear/web/app.py tests/test_settings_api.py
git commit -m "Add write-only secret settings with storage overrides"
```

---

### Task 6: `POST /api/settings/test-gateway`

**Files:**
- Modify: `src/switchgear/web/settings_routes.py`
- Test: `tests/test_settings_api.py` (append)

**Interfaces:**
- Produces: `POST /api/settings/test-gateway` `{gateway_base_url?, gateway_api_key?}` → `{"ok": true, "models": int}` or `{"ok": false, "detail": str}`, always HTTP 200 for reachability results.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_settings_api.py` (respx is already a dev dependency; see `tests/test_gateway.py`):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_settings_api.py -k gateway_test -v`
Expected: FAIL with 404 (route missing)

- [ ] **Step 3: Implement** — in `src/switchgear/web/settings_routes.py`, add `import httpx` at the top, then after `UserSettingsUpdate`:

```python
class GatewayTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_base_url: str = ""
    gateway_api_key: str = ""
```

Inside `register_settings_routes`, add:

```python
    @app.post("/api/settings/test-gateway")
    async def test_gateway(body: GatewayTestRequest,
                           email: str = Depends(auth.require_owner)):
        base = (body.gateway_base_url or state.settings.gateway_base_url).rstrip("/")
        key = body.gateway_api_key or state.settings.gateway_api_key
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{base}/models",
                                        headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            return {"ok": False, "detail": f"connection failed: {type(exc).__name__}"}
        if resp.status_code >= 400:
            return {"ok": False, "detail": f"gateway returned {resp.status_code}"}
        try:
            data = resp.json()
            models = data.get("data", []) if isinstance(data, dict) else data
            count = len(models) if isinstance(models, list) else 0
        except ValueError:
            count = 0
        return {"ok": True, "models": count}
```

- [ ] **Step 4: Run tests**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_settings_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/web/settings_routes.py tests/test_settings_api.py
git commit -m "Add gateway connection test endpoint"
```

---

### Task 7: `POST /api/settings/password`

**Files:**
- Modify: `src/switchgear/web/settings_routes.py`
- Test: `tests/test_settings_api.py` (append)

**Interfaces:**
- Consumes: `auth.hash_password` (Task 1), `auth.verify_password`, `SECURE_KEY` (Task 4).
- Produces: `POST /api/settings/password` `{current_password, new_password}` → `{"ok": true}`; 403 on wrong current password.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_settings_api.py`:

```python
async def test_password_change_verifies_current_and_persists():
    from switchgear.auth import hash_password, verify_password

    storage = MemoryStorage()
    settings = Settings(_env_file=None, owner_email=OWNER, session_secret="s3",
                        local_password_hash=hash_password("old-password"))
    app = create_app(settings=settings, storage=storage, gateway=FakeGateway([]))
    async with client(app) as c:
        bad = await c.post("/api/settings/password",
                           json={"current_password": "nope",
                                 "new_password": "new-password-1"})
        assert bad.status_code == 403
        short = await c.post("/api/settings/password",
                             json={"current_password": "old-password",
                                   "new_password": "short"})
        assert short.status_code == 422
        good = await c.post("/api/settings/password",
                            json={"current_password": "old-password",
                                  "new_password": "new-password-1"})
    assert good.status_code == 200
    effective = app.state.switchgear.settings.local_password_hash
    assert verify_password("new-password-1", effective)
    stored = await storage.get("app-settings", "secure")
    assert stored["local_password_hash"] == effective
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_settings_api.py::test_password_change_verifies_current_and_persists -v`
Expected: FAIL with 404

- [ ] **Step 3: Implement** — in `src/switchgear/web/settings_routes.py`, add `HTTPException` to the fastapi import, then the model:

```python
class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)
```

Inside `register_settings_routes`:

```python
    @app.post("/api/settings/password")
    async def change_password(body: PasswordChangeRequest,
                              email: str = Depends(auth.require_owner)):
        if not auth.verify_password(body.current_password,
                                    state.settings.local_password_hash):
            raise HTTPException(403, "current password is incorrect")
        new_hash = auth.hash_password(body.new_password)
        stored = await state.storage.get(SETTINGS_COLLECTION, SECURE_KEY) or {}
        stored["local_password_hash"] = new_hash
        await state.storage.put(SETTINGS_COLLECTION, SECURE_KEY, stored)
        state.settings.local_password_hash = new_hash
        return {"ok": True}
```

- [ ] **Step 4: Run tests**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_settings_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/web/settings_routes.py tests/test_settings_api.py
git commit -m "Add owner password change endpoint"
```

---

### Task 8: Setup mode — token, claim flow, session-secret auto-generation, app wiring

**Files:**
- Create: `src/switchgear/web/setup_routes.py`
- Modify: `src/switchgear/web/app.py`
- Test: `tests/test_setup_flow.py` (new)

**Interfaces:**
- Consumes: `auth.hash_password`, `auth.sign_session`, `SETTINGS_COLLECTION`/`SECURE_KEY` and `load_secure_overrides` (Tasks 4–5), `DEV_SESSION_SECRET` (Task 2).
- Produces: `is_claimed(settings) -> bool`; `ensure_setup_token(state) -> str`; `ensure_session_secret(state) -> None`; `announce_setup(state) -> None`; routes `GET /setup`, `GET /api/setup/status`, `POST /api/setup/claim`; `register_setup_routes(app, state)`. `SETUP_TOKEN_KEY = "setup-token"`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_setup_flow.py`:

```python
import httpx

from switchgear.auth import hash_password, verify_session
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from switchgear.web.setup_routes import (
    ensure_session_secret,
    ensure_setup_token,
    is_claimed,
)
from tests.fakes import FakeGateway


def make_unclaimed_app(storage=None, **overrides):
    settings = Settings(_env_file=None, **overrides)
    return create_app(settings=settings, storage=storage or MemoryStorage(),
                      gateway=FakeGateway([]))


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://t")


async def test_status_reports_unclaimed_then_claimed():
    app = make_unclaimed_app()
    async with client(app) as c:
        assert (await c.get("/api/setup/status")).json() == {"claimed": False}
    app.state.switchgear.settings.local_password_hash = "scrypt:x"
    async with client(app) as c:
        assert (await c.get("/api/setup/status")).json() == {"claimed": True}


async def test_setup_token_persists_and_env_wins():
    storage = MemoryStorage()
    app = make_unclaimed_app(storage)
    state = app.state.switchgear
    token1 = await ensure_setup_token(state)
    token2 = await ensure_setup_token(state)
    assert token1 == token2 and len(token1) >= 24
    assert (await storage.get("app-settings", "setup-token"))["token"] == token1

    preset = make_unclaimed_app(setup_token="preset-tok")
    assert await ensure_setup_token(preset.state.switchgear) == "preset-tok"


async def test_claim_happy_path_sets_cookie_and_deletes_token():
    storage = MemoryStorage()
    app = make_unclaimed_app(storage)
    state = app.state.switchgear
    token = await ensure_setup_token(state)
    async with client(app) as c:
        response = await c.post("/api/setup/claim", json={
            "token": token, "password": "hunter22-long",
            "owner_email": "me@example.com", "owner_timezone": "America/New_York"})
    assert response.status_code == 200
    assert is_claimed(state.settings)
    assert state.settings.owner_email == "me@example.com"
    assert state.settings.owner_timezone == "America/New_York"
    assert verify_session(state.settings, response.cookies.get("session")) \
        == "me@example.com"
    assert await storage.get("app-settings", "setup-token") is None
    secure = await storage.get("app-settings", "secure")
    assert secure["owner_email"] == "me@example.com"
    assert (await storage.get("app-settings", "user"))["owner_timezone"] \
        == "America/New_York"


async def test_claim_rejects_bad_token_and_short_password(monkeypatch):
    import asyncio as aio
    async def no_sleep(_):
        pass
    monkeypatch.setattr(aio, "sleep", no_sleep)
    app = make_unclaimed_app()
    token = await ensure_setup_token(app.state.switchgear)
    async with client(app) as c:
        bad = await c.post("/api/setup/claim", json={
            "token": "wrong", "password": "hunter22-long",
            "owner_email": "me@example.com"})
        assert bad.status_code == 403
        short = await c.post("/api/setup/claim", json={
            "token": token, "password": "short", "owner_email": "me@example.com"})
        assert short.status_code == 422


async def test_claim_conflicts_when_already_claimed():
    app = make_unclaimed_app(local_password_hash=hash_password("existing-pass"),
                             owner_email="own@x.y")
    async with client(app) as c:
        response = await c.post("/api/setup/claim", json={
            "token": "any", "password": "hunter22-long",
            "owner_email": "me@example.com"})
    assert response.status_code == 409


async def test_session_secret_autogenerated_and_stable():
    storage = MemoryStorage()
    app = make_unclaimed_app(storage)
    await ensure_session_secret(app.state.switchgear)
    first = app.state.switchgear.settings.session_secret
    assert first != "dev-secret-change-me" and len(first) == 64

    app2 = make_unclaimed_app(storage)
    await ensure_session_secret(app2.state.switchgear)
    assert app2.state.switchgear.settings.session_secret == first

    explicit = make_unclaimed_app(MemoryStorage(), session_secret="explicit")
    await ensure_session_secret(explicit.state.switchgear)
    assert explicit.state.switchgear.settings.session_secret == "explicit"


async def test_unclaimed_login_redirects_to_setup():
    app = make_unclaimed_app()
    async with client(app) as c:
        response = await c.get("/login")
    assert response.status_code == 307
    assert response.headers["location"] == "/setup"


async def test_setup_page_redirects_home_when_claimed():
    app = make_unclaimed_app(local_password_hash="scrypt:x", owner_email="o@x.y")
    async with client(app) as c:
        response = await c.get("/setup")
    assert response.status_code == 307
    assert response.headers["location"] == "/"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_setup_flow.py -v`
Expected: FAIL — `ModuleNotFoundError: switchgear.web.setup_routes`

- [ ] **Step 3: Implement** — create `src/switchgear/web/setup_routes.py`:

```python
"""First-run claim flow: an unclaimed instance is configured through a
token-gated browser wizard instead of environment variables (spec:
unified setup). The token is env-preset or generated+persisted, printed
to the logs, and single-use."""

import asyncio
import hmac
import logging
import secrets
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from switchgear import auth
from switchgear.config import DEV_SESSION_SECRET
from switchgear.web.settings_routes import SECURE_KEY, SETTINGS_COLLECTION, SETTINGS_KEY
from switchgear.web.spa import spa_index, spa_response

logger = logging.getLogger(__name__)

SETUP_TOKEN_KEY = "setup-token"


def is_claimed(settings) -> bool:
    return bool(settings.local_password_hash)


async def ensure_setup_token(state) -> str:
    if state.settings.setup_token:
        return state.settings.setup_token
    doc = await state.storage.get(SETTINGS_COLLECTION, SETUP_TOKEN_KEY)
    if doc and doc.get("token"):
        return doc["token"]
    token = secrets.token_urlsafe(24)
    await state.storage.put(SETTINGS_COLLECTION, SETUP_TOKEN_KEY, {"token": token})
    return token


async def ensure_session_secret(state) -> None:
    if state.settings.session_secret != DEV_SESSION_SECRET:
        return
    stored = await state.storage.get(SETTINGS_COLLECTION, SECURE_KEY) or {}
    if not stored.get("session_secret"):
        stored["session_secret"] = secrets.token_hex(32)
        await state.storage.put(SETTINGS_COLLECTION, SECURE_KEY, stored)
    state.settings.session_secret = stored["session_secret"]


async def announce_setup(state) -> None:
    if is_claimed(state.settings):
        return
    token = await ensure_setup_token(state)
    logger.warning("SETUP required — visit %s/setup  token: %s",
                   state.settings.public_base_url.rstrip("/"), token)


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=500)
    password: str = Field(min_length=8, max_length=200)
    owner_email: str = Field(min_length=3, max_length=200, pattern=r".+@.+")
    owner_timezone: str = Field(default="", max_length=100)


def register_setup_routes(app, state) -> None:
    @app.get("/setup")
    async def setup_page():
        if is_claimed(state.settings):
            return RedirectResponse("/", status_code=307)
        if spa_index():
            return spa_response()
        return HTMLResponse(
            "<h1>Switchgear setup</h1><p>Frontend build not found. Claim via "
            "POST /api/setup/claim or configure through environment variables.</p>")

    @app.get("/api/setup/status")
    async def setup_status():
        return {"claimed": is_claimed(state.settings)}

    @app.post("/api/setup/claim")
    async def setup_claim(body: ClaimRequest):
        if is_claimed(state.settings):
            raise HTTPException(409, "instance already configured")
        expected = await ensure_setup_token(state)
        if not hmac.compare_digest(body.token, expected):
            await asyncio.sleep(0.5)
            raise HTTPException(403, "invalid setup token")
        if body.owner_timezone:
            try:
                ZoneInfo(body.owner_timezone)
            except Exception:
                raise HTTPException(400, "unknown timezone") from None
        stored = await state.storage.get(SETTINGS_COLLECTION, SECURE_KEY) or {}
        stored["local_password_hash"] = auth.hash_password(body.password)
        stored["owner_email"] = body.owner_email
        await state.storage.put(SETTINGS_COLLECTION, SECURE_KEY, stored)
        await state.storage.delete(SETTINGS_COLLECTION, SETUP_TOKEN_KEY)
        state.settings.local_password_hash = stored["local_password_hash"]
        state.settings.owner_email = body.owner_email
        if body.owner_timezone:
            user = await state.storage.get(SETTINGS_COLLECTION, SETTINGS_KEY) or {}
            user["owner_timezone"] = body.owner_timezone
            await state.storage.put(SETTINGS_COLLECTION, SETTINGS_KEY, user)
            state.settings.owner_timezone = body.owner_timezone
        response = JSONResponse({"ok": True})
        response.set_cookie("session",
                            auth.sign_session(state.settings, body.owner_email),
                            httponly=True, secure=state.settings.cookie_secure,
                            samesite=state.settings.cookie_samesite,
                            max_age=auth.SESSION_MAX_AGE)
        return response
```

Wire into `src/switchgear/web/app.py`:

1. In lifespan, extend the settings import and add setup calls so the block reads:

```python
        from switchgear.web.settings_routes import (
            load_secure_overrides,
            load_settings_overrides,
        )
        from switchgear.web.setup_routes import announce_setup, ensure_session_secret

        await load_settings_overrides(state)
        await load_secure_overrides(state)
        await ensure_session_secret(state)
        await announce_setup(state)
```

2. In `login_page`, add as the FIRST line of the body:

```python
        if not state.settings.local_password_hash:
            return RedirectResponse("/setup", status_code=307)
```

3. Next to the other `register_*` calls at the bottom:

```python
    from switchgear.web.setup_routes import register_setup_routes

    register_setup_routes(app, state)
```

- [ ] **Step 4: Run tests**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_setup_flow.py tests/test_auth.py tests/test_settings_api.py -q`
Expected: PASS

- [ ] **Step 5: Run the whole backend suite**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
Expected: PASS (fix any test that assumed boot requires a password hash)

- [ ] **Step 6: Commit**

```bash
git add src/switchgear/web/setup_routes.py src/switchgear/web/app.py tests/test_setup_flow.py
git commit -m "Add token-gated first-run setup flow"
```

---

### Task 9: Frontend API types and queries

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/queries/settings.ts`
- Create: `frontend/src/api/queries/setup.ts`
- Test: `frontend/src/api/client.test.ts` untouched; new query hooks are covered through the page tests in Tasks 10–11 (project convention — hooks have no standalone tests).

**Interfaces:**
- Produces (consumed by Tasks 10–11):
  - types: `UserSettings` extended; `UserSettingsUpdate`; `SetupStatus`; `GatewayTestResult`; `ClaimRequest`.
  - `useSaveUserSettings(): UseMutation<UserSettings, UserSettingsUpdate>`
  - `useTestGateway()` — mutation posting `{gateway_base_url?, gateway_api_key?}` → `GatewayTestResult`
  - `useChangePassword()` — mutation posting `{current_password, new_password}` → `{ok: boolean}`
  - `useSetupStatus()`, `useClaim()` from `queries/setup.ts`.

- [ ] **Step 1: Extend `frontend/src/api/types.ts`** — replace the `UserSettings` interface with:

```typescript
export interface UserSettings {
  owner_email: string;
  gateway_base_url: string;
  owner_timezone: string;
  email_backend: "console" | "smtp";
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_from: string;
  smtp_starttls: boolean;
  gateway_api_key_set: boolean;
  smtp_password_set: boolean;
  model_chat: string;
  model_bulk: string;
  model_writing: string;
  run_token_budget: number;
  max_loop_iterations: number;
  resource_max_bytes: number;
  resource_read_chars: number;
  memory_max_chars: number;
  memory_core_max_chars: number;
  memory_recall_k: number;
  memory_recall_floor: number;
  memory_supersede_threshold: number;
  memory_recency_half_life_days: number;
  memory_reflection_min_interval: number;
  channel_body_max_chars: number;
  channel_backfill_max: number;
  channel_reply_rate_per_day: number;
}

export type UserSettingsUpdate =
  Omit<UserSettings, "owner_email" | "gateway_api_key_set" | "smtp_password_set"> & {
    gateway_api_key?: string;
    smtp_password?: string;
  };

export interface SetupStatus {
  claimed: boolean;
}

export interface GatewayTestResult {
  ok: boolean;
  models?: number;
  detail?: string;
}

export interface ClaimRequest {
  token: string;
  password: string;
  owner_email: string;
  owner_timezone?: string;
}
```

- [ ] **Step 2: Extend `frontend/src/api/queries/settings.ts`** — change the save-mutation type and add two hooks (full file):

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../client";
import { GatewayTestResult, OkResponse, UserSettings, UserSettingsUpdate } from "../types";

export function useUserSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => apiGet<UserSettings>("/api/settings") });
}

export function useSaveUserSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: UserSettingsUpdate) =>
      apiSend<UserSettings>("PUT", "/api/settings", settings),
    onSuccess: (settings) => qc.setQueryData(["settings"], settings),
    meta: { inlineError: true },
  });
}

export function useTestGateway() {
  return useMutation({
    mutationFn: (probe: { gateway_base_url?: string; gateway_api_key?: string }) =>
      apiSend<GatewayTestResult>("POST", "/api/settings/test-gateway", probe),
    meta: { inlineError: true },
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      apiSend<OkResponse>("POST", "/api/settings/password", body),
    meta: { inlineError: true },
  });
}

export function useLogout() {
  return useMutation({
    mutationFn: () => apiSend<OkResponse>("POST", "/auth/logout"),
    onSuccess: () => window.location.assign("/login"),
    meta: { inlineError: true },
  });
}
```

- [ ] **Step 3: Create `frontend/src/api/queries/setup.ts`:**

```typescript
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiGet, apiSend } from "../client";
import { ClaimRequest, OkResponse, SetupStatus } from "../types";

export function useSetupStatus() {
  return useQuery({ queryKey: ["setup-status"], queryFn: () => apiGet<SetupStatus>("/api/setup/status") });
}

export function useClaim() {
  return useMutation({
    mutationFn: (body: ClaimRequest) => apiSend<OkResponse>("POST", "/api/setup/claim", body),
    meta: { inlineError: true },
  });
}
```

- [ ] **Step 4: Typecheck and run existing frontend tests**

Run: `cd frontend && npx tsc --noEmit && npm test -- --run`
Expected: tsc clean except `SettingsPage.tsx`/`SettingsPage.test.tsx` errors caused by the widened `UserSettings` (fixed in Task 11 — if the only errors are in those two files, proceed); vitest suite may fail on SettingsPage tests for the same reason. Record which failures exist; Task 11 must clear them.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/queries/settings.ts frontend/src/api/queries/setup.ts
git commit -m "Add setup and gateway config API bindings"
```

---

### Task 10: SetupPage wizard + route

**Files:**
- Create: `frontend/src/pages/SetupPage.tsx`
- Create: `frontend/src/pages/SetupPage.module.css`
- Modify: `frontend/src/router.tsx`
- Test: `frontend/src/pages/SetupPage.test.tsx` (new)

**Interfaces:**
- Consumes: `useSetupStatus`, `useClaim` (Task 9), `useSaveUserSettings`, `useTestGateway`, `useUserSettings` (Task 9).
- Produces: route `/setup` rendered OUTSIDE `AppShell`.

- [ ] **Step 1: Look at an existing page test for harness conventions**

Read `frontend/src/pages/SettingsPage.test.tsx` and `frontend/src/test/utils.tsx` fully before writing the test; reuse their render helper and msw server exactly. The test code below assumes a `renderWithProviders`-style helper and msw `server` from `frontend/src/test/msw.ts` — adapt names to what actually exists.

- [ ] **Step 2: Write the failing tests** — create `frontend/src/pages/SetupPage.test.tsx` (adapt harness imports per Step 1):

```tsx
import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SetupPage from "./SetupPage";
import { server } from "../test/msw";
import { renderPage } from "../test/utils";

function mockUnclaimed() {
  server.use(http.get("/api/setup/status", () =>
    HttpResponse.json({ claimed: false })));
}

test("claim step submits token, email, and password", async () => {
  mockUnclaimed();
  let claimBody: unknown;
  server.use(http.post("/api/setup/claim", async ({ request }) => {
    claimBody = await request.json();
    return HttpResponse.json({ ok: true });
  }));
  renderPage(<SetupPage />, { route: "/setup?token=tok-from-url" });

  await screen.findByText(/claim this instance/i);
  expect(screen.getByLabelText(/setup token/i)).toHaveValue("tok-from-url");
  await userEvent.type(screen.getByLabelText(/email/i), "me@example.com");
  await userEvent.type(screen.getByLabelText(/^password$/i), "hunter22-long");
  await userEvent.type(screen.getByLabelText(/confirm password/i), "hunter22-long");
  await userEvent.click(screen.getByRole("button", { name: /claim/i }));

  await screen.findByText(/model gateway/i);   // advanced to step 2
  expect(claimBody).toMatchObject({
    token: "tok-from-url", owner_email: "me@example.com",
    password: "hunter22-long",
  });
});

test("mismatched passwords block submission", async () => {
  mockUnclaimed();
  renderPage(<SetupPage />, { route: "/setup" });
  await screen.findByText(/claim this instance/i);
  await userEvent.type(screen.getByLabelText(/setup token/i), "t");
  await userEvent.type(screen.getByLabelText(/email/i), "me@example.com");
  await userEvent.type(screen.getByLabelText(/^password$/i), "hunter22-long");
  await userEvent.type(screen.getByLabelText(/confirm password/i), "different");
  await userEvent.click(screen.getByRole("button", { name: /claim/i }));
  await screen.findByText(/passwords do not match/i);
});

test("gateway step tests connection and finishes", async () => {
  mockUnclaimed();
  server.use(
    http.post("/api/setup/claim", () => HttpResponse.json({ ok: true })),
    http.get("/api/settings", () => HttpResponse.json({
      owner_email: "me@example.com", gateway_base_url: "https://openrouter.ai/api/v1",
      owner_timezone: "Etc/UTC", email_backend: "console", smtp_host: "",
      smtp_port: 587, smtp_username: "", smtp_from: "", smtp_starttls: true,
      gateway_api_key_set: false, smtp_password_set: false,
      model_chat: "anthropic/claude-sonnet-4.5", model_bulk: "b", model_writing: "w",
      run_token_budget: 200000, max_loop_iterations: 20, resource_max_bytes: 800000,
      resource_read_chars: 60000, memory_max_chars: 1000, memory_core_max_chars: 6000,
      memory_recall_k: 4, memory_recall_floor: 0.55, memory_supersede_threshold: 0.92,
      memory_recency_half_life_days: 14, memory_reflection_min_interval: 600,
      channel_body_max_chars: 20000, channel_backfill_max: 200,
      channel_reply_rate_per_day: 20,
    })),
    http.post("/api/settings/test-gateway", () =>
      HttpResponse.json({ ok: true, models: 42 })),
    http.put("/api/settings", async ({ request }) =>
      HttpResponse.json(await request.json())),
  );
  renderPage(<SetupPage />, { route: "/setup?token=t" });
  await screen.findByText(/claim this instance/i);
  await userEvent.type(screen.getByLabelText(/email/i), "me@example.com");
  await userEvent.type(screen.getByLabelText(/^password$/i), "hunter22-long");
  await userEvent.type(screen.getByLabelText(/confirm password/i), "hunter22-long");
  await userEvent.click(screen.getByRole("button", { name: /claim/i }));

  await screen.findByText(/model gateway/i);
  await userEvent.type(screen.getByLabelText(/api key/i), "sk-new");
  await userEvent.click(screen.getByRole("button", { name: /test connection/i }));
  await screen.findByText(/connected — 42 models/i);
  await userEvent.click(screen.getByRole("button", { name: /save and finish/i }));
  await screen.findByText(/you're all set/i);
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm test -- --run SetupPage`
Expected: FAIL — module not found

- [ ] **Step 4: Implement** — create `frontend/src/pages/SetupPage.module.css`:

```css
.page {
  max-width: 30rem;
  margin: 10vh auto 0;
  padding: 0 1rem;
}
.card {
  border: 1px solid var(--border, #d0d0d0);
  border-radius: 8px;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.field small { opacity: 0.7; }
.error { color: var(--danger, #b00020); }
.success { color: var(--ok, #1a7f37); }
.actions { display: flex; gap: 0.75rem; align-items: center; margin-top: 0.5rem; }
```

Create `frontend/src/pages/SetupPage.tsx`:

```tsx
import { FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Button from "../components/Button";
import { useClaim, useSetupStatus } from "../api/queries/setup";
import { useSaveUserSettings, useTestGateway, useUserSettings } from "../api/queries/settings";
import styles from "./SetupPage.module.css";

type Step = "claim" | "gateway" | "done";

export default function SetupPage() {
  const status = useSetupStatus();
  const [step, setStep] = useState<Step>("claim");

  if (status.data?.claimed && step === "claim") {
    window.location.assign("/");
    return null;
  }
  if (status.isLoading) return <div className="dim">loading…</div>;

  return (
    <div className={styles.page}>
      {step === "claim" && <ClaimStep onDone={() => setStep("gateway")} />}
      {step === "gateway" && <GatewayStep onDone={() => setStep("done")} />}
      {step === "done" && (
        <section className={styles.card}>
          <h1>You're all set</h1>
          <p>Switchgear is configured. You are logged in.</p>
          <div className={styles.actions}>
            <Button variant="primary" onClick={() => window.location.assign("/")}>
              Open Switchgear
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}

function ClaimStep({ onDone }: { onDone: () => void }) {
  const [params] = useSearchParams();
  const claim = useClaim();
  const [token, setToken] = useState(params.get("token") ?? "");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setLocalError("passwords do not match");
      return;
    }
    setLocalError("");
    claim.mutate(
      { token, password, owner_email: email,
        owner_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
      { onSuccess: onDone },
    );
  }

  return (
    <form className={styles.card} onSubmit={submit}>
      <h1>Claim this instance</h1>
      <p>Use the setup token from the server logs (or your deploy configuration)
        to become the owner.</p>
      <label className={styles.field}>
        <span>Setup token</span>
        <input aria-label="Setup token" value={token}
               onChange={(e) => setToken(e.target.value)} required />
      </label>
      <label className={styles.field}>
        <span>Email</span>
        <input aria-label="Email" type="email" value={email}
               onChange={(e) => setEmail(e.target.value)} required />
      </label>
      <label className={styles.field}>
        <span>Password</span>
        <small>At least 8 characters.</small>
        <input aria-label="Password" type="password" value={password} minLength={8}
               onChange={(e) => setPassword(e.target.value)} required />
      </label>
      <label className={styles.field}>
        <span>Confirm password</span>
        <input aria-label="Confirm password" type="password" value={confirm}
               onChange={(e) => setConfirm(e.target.value)} required />
      </label>
      <div className={styles.actions}>
        <Button type="submit" variant="primary" disabled={claim.isPending}>Claim</Button>
        {localError && <span className={styles.error}>{localError}</span>}
        {claim.error && <span className={styles.error}>{claim.error.message}</span>}
      </div>
    </form>
  );
}

function GatewayStep({ onDone }: { onDone: () => void }) {
  const { data } = useUserSettings();
  const save = useSaveUserSettings();
  const test = useTestGateway();
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState<string | null>(null);

  if (!data) return <div className="dim">loading…</div>;
  const effectiveBase = baseUrl ?? data.gateway_base_url;
  const effectiveModel = model ?? data.model_chat;

  function submit(event: FormEvent) {
    event.preventDefault();
    const { owner_email: _e, gateway_api_key_set: _g, smtp_password_set: _s,
            ...editable } = data!;
    save.mutate(
      { ...editable, gateway_base_url: effectiveBase, model_chat: effectiveModel,
        ...(apiKey ? { gateway_api_key: apiKey } : {}) },
      { onSuccess: onDone },
    );
  }

  return (
    <form className={styles.card} onSubmit={submit}>
      <h1>Model gateway</h1>
      <p>Any OpenAI-compatible endpoint works. You can change this later in
        Settings.</p>
      <label className={styles.field}>
        <span>Base URL</span>
        <input aria-label="Base URL" value={effectiveBase}
               onChange={(e) => setBaseUrl(e.target.value)} required />
      </label>
      <label className={styles.field}>
        <span>API key</span>
        <input aria-label="API key" type="password" value={apiKey}
               onChange={(e) => setApiKey(e.target.value)} />
      </label>
      <label className={styles.field}>
        <span>Chat model</span>
        <input aria-label="Chat model" value={effectiveModel}
               onChange={(e) => setModel(e.target.value)} required />
      </label>
      <div className={styles.actions}>
        <Button onClick={() => test.mutate({ gateway_base_url: effectiveBase,
                                             gateway_api_key: apiKey })}
                disabled={test.isPending} type="button">
          Test connection
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending}>
          Save and finish
        </Button>
        <Button type="button" onClick={onDone}>Skip for now</Button>
      </div>
      {test.data && (test.data.ok
        ? <span className={styles.success}>connected — {test.data.models} models</span>
        : <span className={styles.error}>
            {test.data.detail} (gateways without /models report failure here)
          </span>)}
      {save.error && <span className={styles.error}>{save.error.message}</span>}
    </form>
  );
}
```

Modify `frontend/src/router.tsx` — add the import and a sibling route so `routes` becomes:

```tsx
import SetupPage from "./pages/SetupPage";

export const routes = [
  { path: "/setup", element: <SetupPage /> },
  {
    element: <AppShell />,
    children: [
      /* ...existing children unchanged... */
    ],
  },
];
```

- [ ] **Step 5: Run tests**

Run: `cd frontend && npm test -- --run SetupPage`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SetupPage.tsx frontend/src/pages/SetupPage.module.css frontend/src/pages/SetupPage.test.tsx frontend/src/router.tsx
git commit -m "Add first-run setup wizard page"
```

---

### Task 11: SettingsPage — gateway, email, and account groups

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/pages/SettingsPage.test.tsx` (fix Task 9 fallout + new tests)
- Modify: `frontend/src/pages/SettingsPage.module.css` (only if a class is missing; reuse existing classes first)

**Interfaces:**
- Consumes: `useTestGateway`, `useChangePassword`, `UserSettingsUpdate` (Task 9).

- [ ] **Step 1: Write the failing tests** — append to `frontend/src/pages/SettingsPage.test.tsx` (reuse the file's existing msw fixture, extending its `/api/settings` payload with the new fields from Task 10 Step 2's example):

```tsx
test("gateway group shows write-only key placeholder and test button", async () => {
  renderSettings({ gateway_api_key_set: true });
  await screen.findByLabelText(/gateway base url/i);
  const key = screen.getByLabelText(/gateway api key/i);
  expect(key).toHaveValue("");
  expect(key).toHaveAttribute("placeholder", expect.stringMatching(/configured/i));
  expect(screen.getByRole("button", { name: /test connection/i })).toBeInTheDocument();
});

test("smtp fields hidden for console backend and shown for smtp", async () => {
  renderSettings({ email_backend: "console" });
  await screen.findByLabelText(/email backend/i);
  expect(screen.queryByLabelText(/smtp host/i)).not.toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText(/email backend/i), "smtp");
  expect(screen.getByLabelText(/smtp host/i)).toBeInTheDocument();
});

test("change password posts current and new", async () => {
  let posted: unknown;
  server.use(http.post("/api/settings/password", async ({ request }) => {
    posted = await request.json();
    return HttpResponse.json({ ok: true });
  }));
  renderSettings({});
  await screen.findByLabelText(/current password/i);
  await userEvent.type(screen.getByLabelText(/current password/i), "old-pass-1");
  await userEvent.type(screen.getByLabelText(/^new password$/i), "new-pass-123");
  await userEvent.type(screen.getByLabelText(/confirm new password/i), "new-pass-123");
  await userEvent.click(screen.getByRole("button", { name: /change password/i }));
  await screen.findByText(/password changed/i);
  expect(posted).toEqual({ current_password: "old-pass-1", new_password: "new-pass-123" });
});
```

(`renderSettings(overrides)` = the file's existing render helper with the settings payload merged with `overrides`; create the helper if the file renders inline today.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- --run SettingsPage`
Expected: new tests FAIL; pre-existing tests may also fail from Task 9's type change

- [ ] **Step 3: Implement** — rework `frontend/src/pages/SettingsPage.tsx`:

Structural changes (keep the existing GROUPS rendering for the untouched groups):

1. Draft type: `type EditableSettings = Omit<UserSettings, "owner_email" | "gateway_api_key_set" | "smtp_password_set">;` and strip all three keys when seeding the draft from `data`.
2. Secrets live in separate state, never in the draft:

```tsx
const [gatewayKey, setGatewayKey] = useState("");
const [smtpPassword, setSmtpPassword] = useState("");
```

3. Submit includes secrets only when non-empty, then clears them:

```tsx
function submit(event: FormEvent) {
  event.preventDefault();
  if (!draft) return;
  save.mutate({
    ...draft,
    ...(gatewayKey ? { gateway_api_key: gatewayKey } : {}),
    ...(smtpPassword ? { smtp_password: smtpPassword } : {}),
  }, { onSuccess: () => { setGatewayKey(""); setSmtpPassword(""); } });
}
```

4. New *gateway* section rendered ABOVE the models group (hand-written, not via GROUPS, because it mixes inputs and a button):

```tsx
<section className={styles.section}>
  <h2>gateway</h2>
  <div className={styles.grid}>
    <label className={styles.field}>
      <span>Gateway base URL</span>
      <small>Any OpenAI-compatible endpoint.</small>
      <input aria-label="Gateway base URL" value={draft.gateway_base_url}
             onChange={(e) => { setDraft({ ...draft, gateway_base_url: e.target.value }); save.reset(); }} />
    </label>
    <label className={styles.field}>
      <span>Gateway API key</span>
      <small>Write-only; leave blank to keep the current key.</small>
      <input aria-label="Gateway API key" type="password" value={gatewayKey}
             placeholder={data.gateway_api_key_set ? "configured ✓ — enter to replace" : "not set"}
             onChange={(e) => { setGatewayKey(e.target.value); save.reset(); }} />
    </label>
  </div>
  <div className={styles.actions}>
    <Button type="button" disabled={testGateway.isPending}
            onClick={() => testGateway.mutate({
              gateway_base_url: draft.gateway_base_url,
              gateway_api_key: gatewayKey })}>
      Test connection
    </Button>
    {testGateway.data && (testGateway.data.ok
      ? <span className={styles.success}>connected — {testGateway.data.models} models</span>
      : <span className={styles.error}>{testGateway.data.detail}</span>)}
  </div>
</section>
```

5. New *email* section after "resources & channels":

```tsx
<section className={styles.section}>
  <h2>email</h2>
  <div className={styles.grid}>
    <label className={styles.field}>
      <span>Email backend</span>
      <small>Console logs messages; SMTP delivers them.</small>
      <select aria-label="Email backend" value={draft.email_backend}
              onChange={(e) => { setDraft({ ...draft, email_backend: e.target.value as "console" | "smtp" }); save.reset(); }}>
        <option value="console">console</option>
        <option value="smtp">smtp</option>
      </select>
    </label>
    {draft.email_backend === "smtp" && (<>
      <label className={styles.field}>
        <span>SMTP host</span>
        <input aria-label="SMTP host" value={draft.smtp_host}
               onChange={(e) => { setDraft({ ...draft, smtp_host: e.target.value }); save.reset(); }} />
      </label>
      <label className={styles.field}>
        <span>SMTP port</span>
        <input aria-label="SMTP port" type="number" value={draft.smtp_port}
               onChange={(e) => { setDraft({ ...draft, smtp_port: Number(e.target.value) }); save.reset(); }} />
      </label>
      <label className={styles.field}>
        <span>SMTP username</span>
        <input aria-label="SMTP username" value={draft.smtp_username}
               onChange={(e) => { setDraft({ ...draft, smtp_username: e.target.value }); save.reset(); }} />
      </label>
      <label className={styles.field}>
        <span>SMTP password</span>
        <small>Write-only; leave blank to keep the current password.</small>
        <input aria-label="SMTP password" type="password" value={smtpPassword}
               placeholder={data.smtp_password_set ? "configured ✓ — enter to replace" : "not set"}
               onChange={(e) => { setSmtpPassword(e.target.value); save.reset(); }} />
      </label>
      <label className={styles.field}>
        <span>From address</span>
        <input aria-label="From address" value={draft.smtp_from}
               onChange={(e) => { setDraft({ ...draft, smtp_from: e.target.value }); save.reset(); }} />
      </label>
      <label className={styles.field}>
        <span>STARTTLS</span>
        <select aria-label="STARTTLS" value={String(draft.smtp_starttls)}
                onChange={(e) => { setDraft({ ...draft, smtp_starttls: e.target.value === "true" }); save.reset(); }}>
          <option value="true">enabled</option>
          <option value="false">disabled</option>
        </select>
      </label>
    </>)}
  </div>
</section>
```

6. Account section additions — timezone field in the main form's grid (near the top or in a small *account* group inside the form):

```tsx
<label className={styles.field}>
  <span>Timezone</span>
  <small>Used for schedules and digests.</small>
  <input aria-label="Timezone" list="timezones" value={draft.owner_timezone}
         onChange={(e) => { setDraft({ ...draft, owner_timezone: e.target.value }); save.reset(); }} />
  <datalist id="timezones">
    {Intl.supportedValuesOf("timeZone").map((tz) => <option key={tz} value={tz} />)}
  </datalist>
</label>
```

and a change-password form inside the existing account section (its own `<form>`, since it posts independently):

```tsx
function PasswordForm() {
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (next !== confirm) { setLocalError("passwords do not match"); return; }
    setLocalError("");
    change.mutate({ current_password: current, new_password: next },
                  { onSuccess: () => { setCurrent(""); setNext(""); setConfirm(""); } });
  }

  return (
    <form onSubmit={submit} className={styles.grid}>
      <label className={styles.field}>
        <span>Current password</span>
        <input aria-label="Current password" type="password" value={current}
               onChange={(e) => setCurrent(e.target.value)} required />
      </label>
      <label className={styles.field}>
        <span>New password</span>
        <input aria-label="New password" type="password" value={next} minLength={8}
               onChange={(e) => setNext(e.target.value)} required />
      </label>
      <label className={styles.field}>
        <span>Confirm new password</span>
        <input aria-label="Confirm new password" type="password" value={confirm}
               onChange={(e) => setConfirm(e.target.value)} required />
      </label>
      <div className={styles.actions}>
        <Button type="submit" disabled={change.isPending}>Change password</Button>
        {change.isSuccess && <span className={styles.success}>password changed</span>}
        {(localError || change.error) &&
          <span className={styles.error}>{localError || change.error?.message}</span>}
      </div>
    </form>
  );
}
```

Add `.actions`/`.success`/`.error` styles to `SettingsPage.module.css` only if not already present.

- [ ] **Step 4: Run tests and typecheck**

Run: `cd frontend && npx tsc --noEmit && npm test -- --run`
Expected: everything PASSES, including the failures recorded in Task 9 Step 4

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx frontend/src/pages/SettingsPage.test.tsx frontend/src/pages/SettingsPage.module.css
git commit -m "Add gateway, email, and account settings UI"
```

---

### Task 12: Setup script, env example, docs

**Files:**
- Create: `scripts/setup.sh` (mode 755)
- Modify: `.env.example`, `README.md`, `docs/configuration.md`, `docs/self-hosting.md`, `SECURITY.md`

- [ ] **Step 1: Create `scripts/setup.sh`:**

```bash
#!/usr/bin/env bash
# One-command local setup: env bootstrap, container start, setup-wizard handoff.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${SWITCHGEAR_PORT:-8080}"
BASE="http://127.0.0.1:${PORT}"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "created .env from .env.example"
fi

if ! grep -Eq '^SWITCHGEAR_SESSION_SECRET=.+' .env; then
  if command -v openssl >/dev/null 2>&1; then
    secret="$(openssl rand -hex 32)"
  else
    secret="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  fi
  if grep -q '^SWITCHGEAR_SESSION_SECRET=' .env; then
    sed -i.bak "s|^SWITCHGEAR_SESSION_SECRET=.*|SWITCHGEAR_SESSION_SECRET=${secret}|" .env \
      && rm -f .env.bak
  else
    printf 'SWITCHGEAR_SESSION_SECRET=%s\n' "${secret}" >> .env
  fi
  echo "generated session secret"
fi

docker compose up -d --build

echo -n "waiting for ${BASE}/healthz "
for _ in $(seq 1 60); do
  if curl -fsS "${BASE}/healthz" >/dev/null 2>&1; then
    echo " ok"
    break
  fi
  echo -n "."
  sleep 2
done
curl -fsS "${BASE}/healthz" >/dev/null || {
  echo; echo "service did not become healthy; check: docker compose logs switchgear"
  exit 1
}

claimed="$(curl -fsS "${BASE}/api/setup/status" | grep -o '"claimed":[a-z]*' | cut -d: -f2)"
if [ "${claimed}" = "true" ]; then
  echo "Already configured — open ${BASE}"
  exit 0
fi

token="$(docker compose logs switchgear 2>&1 | grep 'SETUP required' | tail -1 \
  | sed -n 's/.*token: \([^ ]*\).*/\1/p')"
if [ -n "${token}" ]; then
  echo
  echo "Finish setup in your browser:"
  echo "  ${BASE}/setup?token=${token}"
else
  echo "Setup pending but no token found in logs; run: docker compose logs switchgear | grep 'SETUP required'"
fi
```

Then: `chmod +x scripts/setup.sh` and verify with `bash -n scripts/setup.sh`.

- [ ] **Step 2: Replace `.env.example`:**

```bash
# Session secret — auto-filled by scripts/setup.sh; generate manually with:
# openssl rand -hex 32. Required for stable sessions across restarts.
SWITCHGEAR_SESSION_SECRET=

# Everything below is OPTIONAL. On first run Switchgear serves a browser
# setup wizard (/setup) that configures the owner account and model gateway;
# values saved there are stored in the database and take precedence over
# this file. Environment values act as defaults/fallbacks.

# Preset the one-time setup token instead of reading it from the logs
# (useful on Cloud Run/EC2 where logs are a detour):
#SWITCHGEAR_SETUP_TOKEN=

# OpenAI-compatible model gateway (also configurable in the wizard/Settings):
#SWITCHGEAR_GATEWAY_BASE_URL=https://openrouter.ai/api/v1
#SWITCHGEAR_GATEWAY_API_KEY=
#SWITCHGEAR_MODEL_CHAT=anthropic/claude-sonnet-4.5

# Environment-only owner bootstrap (skips the wizard entirely):
#SWITCHGEAR_OWNER_EMAIL=owner@example.com
#SWITCHGEAR_LOCAL_PASSWORD_HASH=   # generate: uv run switchgear hash-password

# Outbound email: console (default) or smtp (also configurable in Settings):
#SWITCHGEAR_EMAIL_BACKEND=console
#SWITCHGEAR_SMTP_HOST=smtp.example.com
#SWITCHGEAR_SMTP_PORT=587
#SWITCHGEAR_SMTP_USERNAME=
#SWITCHGEAR_SMTP_PASSWORD=
#SWITCHGEAR_SMTP_FROM=agent@example.com
```

- [ ] **Step 3: Update `README.md`** — replace the "Five-minute local start" section body with:

> Requirements: Docker with Compose.
>
> (sh code fence) `./scripts/setup.sh`
>
> The script creates `.env`, generates a session secret, starts the container,
> and prints a one-time setup link. Open it to claim the instance (set your
> password and email) and connect an OpenAI-compatible model gateway — that's
> the whole setup. Configuration lives in the database from then on;
> environment variables remain supported as defaults (see
> [configuration](docs/configuration.md)).

(Write the `./scripts/setup.sh` line as a normal ```sh fenced block in the README.)

(Keep the localhost-binding and volume paragraphs; remove the manual
`openssl`/`hash-password` lines.)

- [ ] **Step 4: Update `docs/configuration.md`** — add after the intro paragraph:

```markdown
## Precedence

Values set through the setup wizard or Settings UI are stored in the database
and take precedence over environment variables, which take precedence over
defaults. Secrets saved through the UI (gateway API key, SMTP password,
password hash) are write-only: the API reports only whether they are set.

| Group | Setting | Default | Notes |
|---|---|---|---|
| Setup | `SWITCHGEAR_SETUP_TOKEN` | generated | Presets the one-time claim token; otherwise it is generated and logged on first boot (`SETUP required — … token: …`). |
```

and append the `SWITCHGEAR_SETUP_TOKEN` row into the existing table (or keep the small table above — either way both tables must render).

- [ ] **Step 5: Update `docs/self-hosting.md`** — append:

```markdown
## First-run setup on EC2 / Cloud Run

The container boots unclaimed with only `SWITCHGEAR_SESSION_SECRET` set (and
even that is auto-generated and persisted if omitted — set it explicitly for
stable sessions). Visit `/setup` and enter the one-time token:

- EC2/Docker: `docker logs switchgear | grep 'SETUP required'`
- Cloud Run: `gcloud run services logs read switchgear --region <region> | grep 'SETUP required'`
- Or skip logs entirely: set `SWITCHGEAR_SETUP_TOKEN` at deploy time.

Persistent storage is a prerequisite: mount a volume for SQLite or select the
Firestore backend. Without it the claim (password, gateway key) and the setup
token reset on every cold start. Always front a public deployment with TLS
and keep `SWITCHGEAR_COOKIE_SECURE=true`.
```

- [ ] **Step 6: Update `SECURITY.md`** — append:

```markdown
## Runtime-configured secrets

Secrets entered through the setup wizard or Settings UI (gateway API key,
SMTP password, password hash, auto-generated session secret) are stored
unencrypted in the application database and are never returned by the API.
The database inherits the trust level of the `/data` volume — restrict
access to it. The one-time setup token appears in service logs until the
instance is claimed; if it leaks pre-claim, delete the
`app-settings/setup-token` document (or restart with a fresh
`SWITCHGEAR_SETUP_TOKEN`) to rotate it.
```

- [ ] **Step 7: Verify**

Run: `bash -n scripts/setup.sh && UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
Expected: clean syntax check; suite PASSES

- [ ] **Step 8: Commit**

```bash
git add scripts/setup.sh .env.example README.md docs/configuration.md docs/self-hosting.md SECURITY.md
git commit -m "Add one-command setup script and unified-setup docs"
```

---

### Task 13: Full verification and live smoke test

**Files:** none new (fixes only if something fails)

- [ ] **Step 1: Backend suite + lint**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q && UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src tests`
Expected: PASS, no lint errors

- [ ] **Step 2: Frontend typecheck, tests, build**

Run: `cd frontend && npx tsc --noEmit && npm test -- --run && npm run build`
Expected: all PASS; build emits to `src/switchgear/web/static/app/`

- [ ] **Step 3: Live smoke test of the whole flow** (uses the built SPA from Step 2):

```bash
UV_CACHE_DIR=/tmp/uv-cache SWITCHGEAR_STATE_DIR=/tmp/claude-1000/-home-dylan-switchgear/9c6a92b9-a20f-4355-8e44-1f4feb983024/scratchpad/smoke-state \
  uv run uvicorn switchgear.main:app --port 8931 &
sleep 3
curl -fsS http://127.0.0.1:8931/api/setup/status          # {"claimed":false}
# token from server output:
TOKEN=<paste from the SETUP required log line>
curl -fsS -X POST http://127.0.0.1:8931/api/setup/claim \
  -H 'content-type: application/json' \
  -d "{\"token\":\"$TOKEN\",\"password\":\"smoke-pass-123\",\"owner_email\":\"smoke@x.y\"}" \
  -c /tmp/claude-1000/-home-dylan-switchgear/9c6a92b9-a20f-4355-8e44-1f4feb983024/scratchpad/cookies.txt
curl -fsS http://127.0.0.1:8931/api/setup/status          # {"claimed":true}
curl -fsS -b /tmp/claude-1000/-home-dylan-switchgear/9c6a92b9-a20f-4355-8e44-1f4feb983024/scratchpad/cookies.txt \
  http://127.0.0.1:8931/api/settings | head -c 300        # includes gateway_base_url, no secrets
kill %1
```

Expected: status flips false→true, claim sets a usable session cookie, settings GET works, no secret values in any response.

- [ ] **Step 4: Commit any fixes; verify clean tree**

```bash
git status --short   # expect empty
```

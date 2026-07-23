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

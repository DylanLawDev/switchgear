from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from switchgear import auth
from switchgear.web.spa import spa_index, spa_response


SETTINGS_COLLECTION = "app-settings"
SETTINGS_KEY = "user"
SECURE_KEY = "secure"


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_base_url: str = Field(min_length=8, max_length=500, pattern=r"^https?://")
    owner_timezone: str = Field(min_length=1, max_length=100)
    email_backend: Literal["console", "smtp"]
    smtp_host: str = Field(max_length=500)
    smtp_port: int = Field(ge=1, le=65535)
    smtp_username: str = Field(max_length=500)
    smtp_from: str = Field(max_length=500)
    smtp_starttls: bool
    model_chat: str = Field(min_length=1, max_length=200)
    model_bulk: str = Field(min_length=1, max_length=200)
    model_writing: str = Field(min_length=1, max_length=200)
    run_token_budget: int = Field(ge=1_000, le=2_000_000)
    max_loop_iterations: int = Field(ge=1, le=100)
    resource_max_bytes: int = Field(ge=10_000, le=20_000_000)
    resource_read_chars: int = Field(ge=1_000, le=1_000_000)
    memory_max_chars: int = Field(ge=100, le=100_000)
    memory_core_max_chars: int = Field(ge=500, le=500_000)
    memory_recall_k: int = Field(ge=1, le=100)
    memory_recall_floor: float = Field(ge=0, le=1)
    memory_supersede_threshold: float = Field(ge=0, le=1)
    memory_recency_half_life_days: float = Field(gt=0, le=3650)
    memory_reflection_min_interval: int = Field(ge=0, le=604_800)
    channel_body_max_chars: int = Field(ge=1_000, le=1_000_000)
    channel_backfill_max: int = Field(ge=1, le=10_000)
    channel_reply_rate_per_day: int = Field(ge=1, le=10_000)

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


USER_SETTING_NAMES = tuple(UserSettings.model_fields)


def current_user_settings(settings) -> dict:
    return {name: getattr(settings, name) for name in USER_SETTING_NAMES}


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


async def load_settings_overrides(state) -> None:
    stored = await state.storage.get(SETTINGS_COLLECTION, SETTINGS_KEY)
    if not stored:
        return
    values = UserSettings.model_validate({**current_user_settings(state.settings), **stored})
    for name, value in values.model_dump().items():
        setattr(state.settings, name, value)


class UserSettingsUpdate(UserSettings):
    gateway_api_key: str = Field(default="", max_length=500)
    smtp_password: str = Field(default="", max_length=500)


class GatewayTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_base_url: str = ""
    gateway_api_key: str = ""


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


def register_settings_routes(app, state) -> None:
    @app.get("/settings")
    async def settings_page(email: str = Depends(auth.require_owner)):
        if spa_index():
            return spa_response()
        return RedirectResponse("/", status_code=307)

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

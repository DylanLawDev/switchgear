from fastapi import Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from switchgear import auth
from switchgear.web.spa import spa_index, spa_response


SETTINGS_COLLECTION = "app-settings"
SETTINGS_KEY = "user"


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


USER_SETTING_NAMES = tuple(UserSettings.model_fields)


def current_user_settings(settings) -> dict:
    return {name: getattr(settings, name) for name in USER_SETTING_NAMES}


async def load_settings_overrides(state) -> None:
    stored = await state.storage.get(SETTINGS_COLLECTION, SETTINGS_KEY)
    if not stored:
        return
    values = UserSettings.model_validate({**current_user_settings(state.settings), **stored})
    for name, value in values.model_dump().items():
        setattr(state.settings, name, value)


def register_settings_routes(app, state) -> None:
    @app.get("/settings")
    async def settings_page(email: str = Depends(auth.require_owner)):
        if spa_index():
            return spa_response()
        return RedirectResponse("/", status_code=307)

    @app.get("/api/settings")
    async def get_user_settings(email: str = Depends(auth.require_owner)):
        return {**current_user_settings(state.settings), "owner_email": email}

    @app.put("/api/settings")
    async def put_user_settings(body: UserSettings,
                                email: str = Depends(auth.require_owner)):
        values = body.model_dump()
        await state.storage.put(SETTINGS_COLLECTION, SETTINGS_KEY, values)
        for name, value in values.items():
            setattr(state.settings, name, value)
        return {**values, "owner_email": email}

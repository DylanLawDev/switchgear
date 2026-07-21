import secrets

from fastapi import Depends, HTTPException, Request

from switchgear.config import Settings, get_settings

async def require_cron(request: Request, settings: Settings = Depends(get_settings)) -> str:
    provided = request.headers.get("x-cron-secret")
    if settings.cron_secret and provided and secrets.compare_digest(
            provided, settings.cron_secret):
        return "secret"
    raise HTTPException(401, "cron authentication required")

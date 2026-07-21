"""Locate/serve the built SPA (spec §6.2 serving contract).

The React build lands in web/static/app/ (assets auto-served at /static/app/
by the existing StaticFiles mount). Until index.html exists there, every page
route falls back to the legacy Jinja UI, so the app works in both worlds."""

from pathlib import Path

from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).parent / "static"


def spa_index() -> Path | None:
    p = STATIC_DIR / "app" / "index.html"
    return p if p.is_file() else None


def spa_response() -> FileResponse:
    return FileResponse(spa_index(), media_type="text/html",
                        headers={"Cache-Control": "no-cache"})

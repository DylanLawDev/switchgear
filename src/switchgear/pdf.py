from abc import ABC, abstractmethod
from pathlib import Path

from switchgear.config import Settings


class PdfRenderer(ABC):
    @abstractmethod
    async def render_pdf(self, html: str, out_path: str) -> str | None: ...


class NullPdfRenderer(PdfRenderer):
    """HTML-only deployments: no PDF artifact is produced."""

    async def render_pdf(self, html: str, out_path: str) -> str | None:
        return None


class ChromiumPdfRenderer(PdfRenderer):
    """Renders HTML to PDF via headless Chromium (Playwright).

    Playwright is an optional dependency (`uv sync --extra browser`) and is
    only imported lazily inside `render_pdf`, so importing this module (and
    running the default test/install path) never requires it. Tests inject a
    `launcher` — a zero-arg callable returning an async context manager that
    mimics `playwright.async_api.async_playwright()` — so no real browser is
    ever launched in CI.
    """

    def __init__(self, launcher=None):
        self._launcher = launcher

    async def render_pdf(self, html: str, out_path: str) -> str | None:
        launcher = self._launcher
        if launcher is None:
            try:
                from playwright.async_api import async_playwright as launcher
            except ImportError:
                raise RuntimeError(
                    "pdf backend 'chromium' requires the browser extra: "
                    "uv sync --extra browser && uv run playwright install chromium"
                ) from None

        async with launcher() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html)
            await page.pdf(path=out_path, format="A4")
            await browser.close()
        return out_path


def get_pdf_renderer(settings: Settings) -> PdfRenderer:
    if settings.pdf_backend == "chromium":
        return ChromiumPdfRenderer()
    return NullPdfRenderer()


def resume_artifact_dir(settings: Settings) -> Path:
    d = Path(settings.state_dir) / "artifacts" / "resumes"
    d.mkdir(parents=True, exist_ok=True)
    return d

import sys

import pytest

from switchgear.config import Settings
from switchgear.pdf import (
    ChromiumPdfRenderer,
    NullPdfRenderer,
    get_pdf_renderer,
    resume_artifact_dir,
)


async def test_null_renderer_returns_none():
    result = await NullPdfRenderer().render_pdf("<html>hi</html>", "/tmp/out.pdf")
    assert result is None


def test_get_pdf_renderer_selects_chromium():
    s = Settings(_env_file=None, pdf_backend="chromium")
    assert isinstance(get_pdf_renderer(s), ChromiumPdfRenderer)


def test_get_pdf_renderer_defaults_to_null():
    assert isinstance(get_pdf_renderer(Settings(_env_file=None, pdf_backend="none")), NullPdfRenderer)
    assert isinstance(get_pdf_renderer(Settings(_env_file=None, pdf_backend="bogus")), NullPdfRenderer)


class FakePage:
    def __init__(self):
        self.set_content_calls: list[str] = []
        self.pdf_calls: list[dict] = []

    async def set_content(self, html: str) -> None:
        self.set_content_calls.append(html)

    async def pdf(self, path: str, format: str) -> None:
        self.pdf_calls.append({"path": path, "format": format})


class FakeBrowser:
    def __init__(self, page: FakePage):
        self._page = page
        self.closed = False

    async def new_page(self):
        return self._page

    async def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser):
        self._browser = browser

    async def launch(self):
        return self._browser


class FakePlaywright:
    def __init__(self, browser: FakeBrowser):
        self.chromium = FakeChromium(browser)


class FakePlaywrightContext:
    def __init__(self, browser: FakeBrowser):
        self._browser = browser

    async def __aenter__(self):
        return FakePlaywright(self._browser)

    async def __aexit__(self, exc_type, exc, tb):
        return False


def make_fake_launcher(page: FakePage, browser: FakeBrowser):
    def launcher():
        return FakePlaywrightContext(browser)

    return launcher


async def test_chromium_renders_via_injected_launcher(tmp_path):
    page = FakePage()
    browser = FakeBrowser(page)
    launcher = make_fake_launcher(page, browser)
    renderer = ChromiumPdfRenderer(launcher=launcher)
    out_path = str(tmp_path / "resume.pdf")

    result = await renderer.render_pdf("<html>résumé</html>", out_path)

    assert result == out_path
    assert page.set_content_calls == ["<html>résumé</html>"]
    assert page.pdf_calls == [{"path": out_path, "format": "A4"}]
    assert browser.closed is True


async def test_chromium_without_launcher_raises_when_playwright_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    renderer = ChromiumPdfRenderer()
    with pytest.raises(RuntimeError, match="--extra browser"):
        await renderer.render_pdf("<html></html>", "/tmp/out.pdf")


def test_resume_artifact_dir_creates_directory(tmp_path):
    s = Settings(_env_file=None, state_dir=str(tmp_path / "state"))
    d = resume_artifact_dir(s)
    assert d == tmp_path / "state" / "artifacts" / "resumes"
    assert d.is_dir()

from abc import ABC, abstractmethod
from pathlib import Path

from switchgear.config import Settings

DEFAULT_SUBMIT_SELECTOR = "button[type=submit], input[type=submit]"


class BrowserSession(ABC):
    @abstractmethod
    async def goto(self, url: str) -> dict: ...

    @abstractmethod
    async def read(self) -> dict: ...

    @abstractmethod
    async def fill(self, selector: str, value: str) -> dict: ...

    @abstractmethod
    async def click(self, selector: str) -> dict: ...

    @abstractmethod
    async def screenshot(self, out_path: str) -> str: ...

    @abstractmethod
    async def upload(self, selector: str, file_path: str) -> dict: ...

    @abstractmethod
    async def submit_form(self, selector: str | None = None) -> dict: ...

    @abstractmethod
    async def close(self) -> None: ...


class PlaywrightBrowserSession(BrowserSession):
    """Drives a single page via Playwright (or an injected fake for tests).

    Playwright is an optional dependency (`uv sync --extra browser`) and is
    only imported lazily inside `start()` when no page is injected, so
    importing this module (and running the default test/install path) never
    requires it. Tests inject a fake page object directly, so no real
    browser is ever launched in CI.
    """

    def __init__(self, page=None):
        self._page = page
        self._browser = None
        self._playwright_cm = None

    async def start(self) -> "PlaywrightBrowserSession":
        if self._page is not None:
            return self
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "browser tool requires the browser extra: "
                "uv sync --extra browser && uv run playwright install chromium"
            ) from None

        self._playwright_cm = async_playwright()
        p = await self._playwright_cm.__aenter__()
        self._browser = await p.chromium.launch()
        self._page = await self._browser.new_page()
        return self

    async def goto(self, url: str) -> dict:
        response = await self._page.goto(url)
        status = getattr(response, "status", None) if response is not None else None
        title = await self._page.title()
        page_url = getattr(self._page, "url", None) or url
        return {"status": status, "title": title, "url": page_url}

    async def read(self) -> dict:
        elements = await self._page.query_selector_all("input, textarea, select")
        fields = []
        for index, el in enumerate(elements):
            fields.append(await self._describe_field(el, index))
        text = await self._page.inner_text("body")
        return {
            "url": getattr(self._page, "url", None),
            "title": await self._page.title(),
            "text": text[:8000],
            "fields": fields,
        }

    async def _describe_field(self, el, index: int) -> dict:
        try:
            tag = (await el.evaluate("el => el.tagName.toLowerCase()")) or "input"
        except Exception:
            tag = "input"

        el_id = await el.get_attribute("id")
        name = await el.get_attribute("name")
        el_type = (await el.get_attribute("type")) or tag
        placeholder = await el.get_attribute("placeholder")
        aria_label = await el.get_attribute("aria-label")

        if el_id:
            selector = f"#{el_id}"
        elif name:
            selector = f'[name="{name}"]'
        else:
            selector = f"{tag}:nth-of-type({index + 1})"

        label = aria_label or placeholder or name or el_id or selector

        field = {"selector": selector, "tag": tag, "type": el_type, "label": label,
                  "value": await self._field_value(el)}

        if tag == "select":
            options = await self._field_options(el)
            if options is not None:
                field["options"] = options

        return field

    @staticmethod
    async def _field_value(el):
        if not hasattr(el, "input_value"):
            return None
        try:
            return await el.input_value()
        except Exception:
            return None

    @staticmethod
    async def _field_options(el):
        if not hasattr(el, "query_selector_all"):
            return None
        try:
            options = await el.query_selector_all("option")
        except Exception:
            return None
        out = []
        for opt in options:
            out.append({"value": await opt.get_attribute("value"), "label": await opt.inner_text()})
        return out

    async def fill(self, selector: str, value: str) -> dict:
        await self._page.fill(selector, value)
        return {"selector": selector, "value": value}

    async def click(self, selector: str) -> dict:
        await self._page.click(selector)
        return {"selector": selector}

    async def screenshot(self, out_path: str) -> str:
        await self._page.screenshot(path=out_path)
        return out_path

    async def upload(self, selector: str, file_path: str) -> dict:
        await self._page.set_input_files(selector, file_path)
        return {"selector": selector, "file_path": file_path}

    async def submit_form(self, selector: str | None = None) -> dict:
        target = selector or DEFAULT_SUBMIT_SELECTOR
        await self._page.click(target)
        return {"selector": target}

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright_cm is not None:
            await self._playwright_cm.__aexit__(None, None, None)
        elif self._page is not None and hasattr(self._page, "close"):
            await self._page.close()


class BrowserManager:
    """Owns a single lazily-created `BrowserSession` for the app's lifetime."""

    def __init__(self, settings: Settings, session_factory=None):
        self._settings = settings
        self._session_factory = session_factory or self._default_factory
        self._session: BrowserSession | None = None

    @staticmethod
    async def _default_factory() -> BrowserSession:
        session = PlaywrightBrowserSession()
        await session.start()
        return session

    async def session(self) -> BrowserSession:
        if self._session is None:
            self._session = await self._session_factory()
        return self._session

    async def reset(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def screenshot_dir(self) -> Path:
        d = Path(self._settings.state_dir) / "artifacts" / "screenshots"
        d.mkdir(parents=True, exist_ok=True)
        return d

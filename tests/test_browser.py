import sys

import pytest

from switchgear.browser import BrowserManager, PlaywrightBrowserSession
from switchgear.config import Settings


class FakeResponse:
    def __init__(self, status: int):
        self.status = status


class FakeElement:
    def __init__(self, tag: str, attrs: dict | None = None, value: str | None = None,
                 options: list[dict] | None = None, has_input_value: bool = True):
        self._tag = tag
        self._attrs = attrs or {}
        self._value = value
        self._options = options
        self._has_input_value = has_input_value

    async def evaluate(self, _script: str) -> str:
        return self._tag

    async def get_attribute(self, name: str) -> str | None:
        return self._attrs.get(name)

    async def input_value(self) -> str:
        if not self._has_input_value:
            raise Exception("no value")
        return self._value or ""

    async def query_selector_all(self, _selector: str) -> list["FakeOption"]:
        if self._options is None:
            raise Exception("no options")
        return [FakeOption(o["value"], o["label"]) for o in self._options]


class FakeOption:
    def __init__(self, value: str, label: str):
        self._value = value
        self._label = label

    async def get_attribute(self, name: str) -> str | None:
        return self._value if name == "value" else None

    async def inner_text(self) -> str:
        return self._label


class FakePage:
    def __init__(self, elements: list[FakeElement] | None = None,
                 body_text: str = "hello world", title: str = "Page Title"):
        self.url = None
        self._title = title
        self._elements = elements or []
        self._body_text = body_text
        self.goto_calls: list[str] = []
        self.fill_calls: list[tuple[str, str]] = []
        self.click_calls: list[str] = []
        self.screenshot_calls: list[str] = []
        self.upload_calls: list[tuple[str, str]] = []
        self.closed = False

    async def goto(self, url: str):
        self.goto_calls.append(url)
        self.url = url
        return FakeResponse(200)

    async def title(self) -> str:
        return self._title

    async def inner_text(self, selector: str) -> str:
        assert selector == "body"
        return self._body_text

    async def query_selector_all(self, selector: str) -> list[FakeElement]:
        assert selector == "input, textarea, select"
        return self._elements

    async def fill(self, selector: str, value: str) -> None:
        self.fill_calls.append((selector, value))

    async def click(self, selector: str) -> None:
        self.click_calls.append(selector)

    async def screenshot(self, path: str) -> None:
        self.screenshot_calls.append(path)

    async def set_input_files(self, selector: str, file_path: str) -> None:
        self.upload_calls.append((selector, file_path))

    async def close(self) -> None:
        self.closed = True


async def test_goto_returns_status_title_url():
    page = FakePage(title="Home")
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    out = await session.goto("https://example.com")

    assert page.goto_calls == ["https://example.com"]
    assert out == {"status": 200, "title": "Home", "url": "https://example.com"}


async def test_read_prefers_id_selector():
    el = FakeElement("input", {"id": "email", "type": "email", "aria-label": "Email"},
                     value="me@example.com")
    page = FakePage(elements=[el])
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    out = await session.read()

    assert out["url"] is None
    assert out["title"] == "Page Title"
    assert out["text"] == "hello world"
    assert out["fields"] == [{
        "selector": "#email", "tag": "input", "type": "email", "label": "Email",
        "value": "me@example.com",
    }]


async def test_read_falls_back_to_name_then_tag_index_selector():
    named = FakeElement("input", {"name": "phone", "placeholder": "Phone number"},
                         value="555", has_input_value=True)
    bare = FakeElement("textarea", {}, value="notes")
    page = FakePage(elements=[named, bare])
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    out = await session.read()

    assert out["fields"][0]["selector"] == '[name="phone"]'
    assert out["fields"][0]["label"] == "Phone number"
    assert out["fields"][1]["selector"] == "textarea:nth-of-type(2)"


async def test_read_includes_select_options_when_available():
    select_el = FakeElement("select", {"id": "country"},
                             options=[{"value": "us", "label": "United States"},
                                      {"value": "ca", "label": "Canada"}])
    page = FakePage(elements=[select_el])
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    out = await session.read()

    assert out["fields"][0]["options"] == [
        {"value": "us", "label": "United States"},
        {"value": "ca", "label": "Canada"},
    ]


async def test_read_caps_visible_text_at_8000_chars():
    page = FakePage(body_text="x" * 9000)
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    out = await session.read()

    assert len(out["text"]) == 8000


async def test_fill_delegates_to_page():
    page = FakePage()
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    out = await session.fill("#name", "Ada")

    assert page.fill_calls == [("#name", "Ada")]
    assert out == {"selector": "#name", "value": "Ada"}


async def test_click_delegates_to_page():
    page = FakePage()
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    out = await session.click("#next")

    assert page.click_calls == ["#next"]
    assert out == {"selector": "#next"}


async def test_screenshot_delegates_to_page():
    page = FakePage()
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    out = await session.screenshot("/tmp/out.png")

    assert page.screenshot_calls == ["/tmp/out.png"]
    assert out == "/tmp/out.png"


async def test_upload_delegates_to_page():
    page = FakePage()
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    out = await session.upload("#resume", "/tmp/resume.pdf")

    assert page.upload_calls == [("#resume", "/tmp/resume.pdf")]
    assert out == {"selector": "#resume", "file_path": "/tmp/resume.pdf"}


async def test_submit_form_defaults_to_generic_submit_selector():
    page = FakePage()
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    out = await session.submit_form()

    assert page.click_calls == ["button[type=submit], input[type=submit]"]
    assert out == {"selector": "button[type=submit], input[type=submit]"}


async def test_submit_form_uses_explicit_selector():
    page = FakePage()
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    out = await session.submit_form("#apply-btn")

    assert page.click_calls == ["#apply-btn"]
    assert out == {"selector": "#apply-btn"}


async def test_close_delegates_to_injected_page():
    page = FakePage()
    session = PlaywrightBrowserSession(page=page)
    await session.start()

    await session.close()

    assert page.closed is True


async def test_start_without_injected_page_raises_when_playwright_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    session = PlaywrightBrowserSession()
    with pytest.raises(RuntimeError, match="--extra browser"):
        await session.start()


async def test_manager_creates_session_once_and_reuses_it(tmp_path):
    page = FakePage()
    made = []

    async def factory():
        session = PlaywrightBrowserSession(page=page)
        await session.start()
        made.append(session)
        return session

    manager = BrowserManager(Settings(_env_file=None, state_dir=str(tmp_path / "state")),
                             session_factory=factory)

    s1 = await manager.session()
    s2 = await manager.session()

    assert s1 is s2
    assert len(made) == 1


async def test_manager_reset_closes_session_and_drops_reference(tmp_path):
    page = FakePage()

    async def factory():
        session = PlaywrightBrowserSession(page=page)
        await session.start()
        return session

    manager = BrowserManager(Settings(_env_file=None, state_dir=str(tmp_path / "state")),
                             session_factory=factory)
    s1 = await manager.session()

    await manager.reset()

    assert page.closed is True
    s2 = await manager.session()
    assert s2 is not s1


async def test_manager_screenshot_dir_creates_directory(tmp_path):
    manager = BrowserManager(Settings(_env_file=None, state_dir=str(tmp_path / "state")))

    d = manager.screenshot_dir

    assert d == tmp_path / "state" / "artifacts" / "screenshots"
    assert d.is_dir()

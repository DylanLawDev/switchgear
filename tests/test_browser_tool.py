import json

import pytest

from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.tools import build_registry
from switchgear.tools.base import ToolRegistry
from switchgear.tools.browser_tool import make_browser_tool

S = Settings(_env_file=None)


class FakeGateway:
    pass


class RecordingSession:
    def __init__(self):
        self.calls: list[tuple] = []

    async def goto(self, url):
        self.calls.append(("goto", url))
        return {"status": 200, "title": "T", "url": url}

    async def read(self):
        self.calls.append(("read",))
        return {"url": "u", "title": "T", "text": "body", "fields": []}

    async def fill(self, selector, value):
        self.calls.append(("fill", selector, value))
        return {"selector": selector, "value": value}

    async def click(self, selector):
        self.calls.append(("click", selector))
        return {"selector": selector}

    async def screenshot(self, out_path):
        self.calls.append(("screenshot", out_path))
        return out_path

    async def upload(self, selector, file_path):
        self.calls.append(("upload", selector, file_path))
        return {"selector": selector, "file_path": file_path}

    async def submit_form(self, selector=None):
        self.calls.append(("submit_form", selector))
        return {"selector": selector}

    async def close(self):
        pass


class FakeManager:
    def __init__(self, session, screenshot_dir):
        self._session = session
        self.screenshot_dir = screenshot_dir

    async def session(self):
        return self._session


def build(storage, session=None, screenshot_dir=None):
    session = session or RecordingSession()
    manager = FakeManager(session, screenshot_dir)
    reg = ToolRegistry()
    reg.register(make_browser_tool(manager, storage))
    return reg, session, manager


async def test_goto_delegates_and_audits(tmp_path):
    storage = MemoryStorage()
    reg, session, _ = build(storage, screenshot_dir=tmp_path)

    out = json.loads(await reg.execute("browser", {"op": "goto", "url": "https://x.test"}))

    assert out == {"status": 200, "title": "T", "url": "https://x.test"}
    audit = await storage.query("audit")
    assert len(audit) == 1
    assert audit[0]["tool"] == "browser"
    assert audit[0]["op"] == "goto"
    assert audit[0]["detail"] == "https://x.test"
    assert "at" in audit[0]


async def test_goto_requires_url():
    storage = MemoryStorage()
    reg, _, _ = build(storage)

    out = json.loads(await reg.execute("browser", {"op": "goto"}))

    assert "error" in out
    assert await storage.query("audit") == []


async def test_read_does_not_audit():
    storage = MemoryStorage()
    reg, session, _ = build(storage)

    out = json.loads(await reg.execute("browser", {"op": "read"}))

    assert out["text"] == "body"
    assert session.calls == [("read",)]
    assert await storage.query("audit") == []


async def test_fill_requires_selector_and_value_and_audits_selector():
    storage = MemoryStorage()
    reg, _, _ = build(storage)

    missing = json.loads(await reg.execute("browser", {"op": "fill", "selector": "#a"}))
    assert "error" in missing

    out = json.loads(await reg.execute(
        "browser", {"op": "fill", "selector": "#a", "value": "hi"}))
    assert out == {"selector": "#a", "value": "hi"}
    audit = await storage.query("audit")
    assert len(audit) == 1
    assert audit[0]["op"] == "fill"
    assert audit[0]["detail"] == "#a"


async def test_click_requires_selector_and_audits():
    storage = MemoryStorage()
    reg, _, _ = build(storage)

    missing = json.loads(await reg.execute("browser", {"op": "click"}))
    assert "error" in missing

    out = json.loads(await reg.execute("browser", {"op": "click", "selector": "#next"}))
    assert out == {"selector": "#next"}
    audit = await storage.query("audit")
    assert audit[0]["op"] == "click"
    assert audit[0]["detail"] == "#next"


async def test_upload_requires_selector_and_file_path_and_audits():
    storage = MemoryStorage()
    reg, _, _ = build(storage)

    missing = json.loads(await reg.execute("browser", {"op": "upload", "selector": "#r"}))
    assert "error" in missing

    out = json.loads(await reg.execute(
        "browser", {"op": "upload", "selector": "#r", "file_path": "/tmp/r.pdf"}))
    assert out == {"selector": "#r", "file_path": "/tmp/r.pdf"}
    audit = await storage.query("audit")
    assert audit[0]["op"] == "upload"
    assert audit[0]["detail"] == "#r"


async def test_screenshot_writes_expected_filename_and_does_not_audit(tmp_path):
    storage = MemoryStorage()
    reg, session, manager = build(storage, screenshot_dir=tmp_path)

    out = json.loads(await reg.execute("browser", {"op": "screenshot"}))

    assert "file" in out
    assert out["file"].startswith("shot-") and out["file"].endswith(".png")
    assert len(out["file"]) == len("shot-") + 10 + len(".png")
    assert session.calls[0][0] == "screenshot"
    assert session.calls[0][1] == str(tmp_path / out["file"])
    assert await storage.query("audit") == []


async def test_unknown_op_errors():
    storage = MemoryStorage()
    reg, _, _ = build(storage)

    out = json.loads(await reg.execute("browser", {"op": "bogus"}))

    assert "error" in out


async def test_submit_op_is_rejected():
    storage = MemoryStorage()
    reg, session, _ = build(storage)

    out = json.loads(await reg.execute("browser", {"op": "submit"}))

    assert "error" in out
    assert not any(c[0] == "submit_form" for c in session.calls)
    assert await storage.query("audit") == []


def test_browser_schema_has_no_submit_op():
    storage = MemoryStorage()
    reg, _, _ = build(storage)

    schema = reg.schemas(["browser"])[0]
    op_enum = schema["function"]["parameters"]["properties"]["op"]["enum"]

    assert "submit" not in op_enum
    assert set(op_enum) == {"goto", "read", "fill", "click", "screenshot", "upload"}


def test_build_registry_registers_browser_only_when_manager_provided():
    storage = MemoryStorage()
    gw = FakeGateway()

    without = build_registry(S, storage, gw)
    with pytest.raises(KeyError):
        without.get("browser")

    manager = FakeManager(RecordingSession(), None)
    with_manager = build_registry(S, storage, gw, browser_manager=manager)
    assert with_manager.get("browser").name == "browser"

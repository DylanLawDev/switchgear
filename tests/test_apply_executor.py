import json

import pytest

from switchgear.config import Settings
from switchgear.pdf import resume_artifact_dir
from switchgear.storage.memory import MemoryStorage
from switchgear.workflows.actions import ExecutionAmbiguous, ExecutionFailed
from switchgear.workflows.plugins.apply import SubmitApplicationExecutor, _parse_fill_result
from switchgear.workflows.plugins.tailor import TailorResumeGenerator

ITEM = {"key": "job-1", "title": "Backend Engineer", "company": "Globex",
        "url": "https://boards.example.com/job/1"}


class FakeRegistry:
    def __init__(self, result_text: str, ok=True):
        self.result_text, self.ok = result_text, ok
        self.calls = []

    async def execute(self, name, args):
        self.calls.append((name, args))
        return json.dumps({"ok": self.ok, "result": self.result_text,
                           "usage": 10, "tool_calls": [], "error": None})


class FakeSession:
    def __init__(self, fail_fill=False, fail_submit=False, fail_screenshot=False):
        self.fail_fill, self.fail_submit = fail_fill, fail_submit
        self.fail_screenshot = fail_screenshot
        self.filled, self.uploaded, self.shots = [], [], []
        self.submitted = False

    async def goto(self, url):
        return {"status": 200}

    async def fill(self, selector, value):
        if self.fail_fill:
            raise RuntimeError("no such element")
        self.filled.append((selector, value))

    async def upload(self, selector, path):
        self.uploaded.append((selector, path))

    async def submit_form(self, selector=None):
        if self.fail_submit:
            raise RuntimeError("click timeout")
        self.submitted = True

    async def screenshot(self, path):
        if self.fail_screenshot:
            raise RuntimeError("no screenshot")
        self.shots.append(path)


class FakeBrowserManager:
    def __init__(self, session, tmp_path):
        self._session = session
        self.reset_calls = 0
        self.screenshot_dir = tmp_path / "shots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    async def reset(self):
        self.reset_calls += 1

    async def session(self):
        return self._session


def settings(tmp_path):
    return Settings(_env_file=None, state_dir=str(tmp_path / "state"))


def executor(tmp_path, registry=None, session=None):
    session = session or FakeSession()
    return SubmitApplicationExecutor(
        MemoryStorage(), FakeBrowserManager(session, tmp_path),
        registry or FakeRegistry("{}"), settings(tmp_path)), session


# ---------- _parse_fill_result (behavior preserved from apply/service.py) ----------


def test_parse_strips_code_fences_and_sanitizes():
    raw = '```json\n{"fields": [{"selector": "#n", "value": "x", "hostile": 1}],' \
          ' "notes": "ok", "screenshot": "s.png", "status": "approved"}\n```'
    fields, notes, screenshot, error = _parse_fill_result(raw)
    assert fields[0]["selector"] == "#n" and "hostile" not in fields[0]
    assert notes == "ok" and screenshot == "s.png" and error is None


def test_parse_garbage_returns_note_and_error():
    fields, notes, screenshot, error = _parse_fill_result("not json at all")
    assert fields == [] and screenshot is None
    assert "manually" in notes and error is not None


def test_parse_rejects_traversal_screenshot_names():
    raw = json.dumps({"fields": [], "notes": "", "screenshot": "../../etc/passwd"})
    assert _parse_fill_result(raw)[2] is None


# ---------- draft ----------


async def test_draft_spawns_scoped_subagent_and_returns_fields(tmp_path):
    reply = json.dumps({"fields": [{"selector": "#name", "label": "Name",
                                    "value": "Alex", "source": "profile",
                                    "needs_you": False, "kind": "text"}],
                        "notes": "", "screenshot": "form.png"})
    reg = FakeRegistry(reply)
    ex, _ = executor(tmp_path, registry=reg)
    result = await ex.draft(ITEM)
    name, args = reg.calls[0]
    assert name == "spawn_subagent"
    assert args["tools"] == ["browser", "resources"]
    assert "https://boards.example.com/job/1" in args["task"]
    assert result.fields[0]["selector"] == "#name"
    assert result.extra["job_title"] == "Backend Engineer"
    assert result.extra["company"] == "Globex"
    assert result.extra["apply_url"] == ITEM["url"]
    assert result.extra["screenshot"] == "form.png"


async def test_draft_includes_resume_context_when_available(tmp_path):
    reg = FakeRegistry(json.dumps({"fields": [], "notes": "", "screenshot": None}))
    ex, _ = executor(tmp_path, registry=reg)
    await ex._db.put("resumes", "r1", {"rid": "r1", "job_key": "job-1",
                                       "html_file": "r1.html", "created_at": 5.0,
                                       "keyword_report": {"hit": ["python"]}})
    await ex.draft(ITEM)
    assert "r1.html" in (reg.calls[0][1].get("context") or "")


# ---------- execute ----------


def record(tmp_path=None, **overrides):
    rec = {"key": "act-1", "job_key": "job-1", "apply_url": ITEM["url"],
           "status": "executing", "notes": "", "fields": [
               {"selector": "#name", "label": "Name", "value": "Alex",
                "source": "profile", "needs_you": False, "kind": "text"},
               {"selector": "#skip", "label": "Skip", "value": "",
                "source": "agent", "needs_you": True, "kind": "text"}]}
    rec.update(overrides)
    return rec


async def test_execute_fills_skips_needs_you_submits_screenshots(tmp_path):
    ex, session = executor(tmp_path)
    updates = await ex.execute(record())
    assert session.filled == [("#name", "Alex")]
    assert session.submitted is True
    assert updates["confirmation_screenshot"] == "confirm-act-1.png"


async def test_execute_uploads_file_fields_from_artifact_dir(tmp_path):
    ex, session = executor(tmp_path)
    artifact_dir = resume_artifact_dir(settings(tmp_path))
    (artifact_dir / "r1.pdf").write_bytes(b"pdf")
    rec = record(fields=[{"selector": "#cv", "label": "CV", "value": "r1.pdf",
                          "source": "resume", "needs_you": False, "kind": "file"}])
    await ex.execute(rec)
    assert session.uploaded[0][0] == "#cv"
    assert session.uploaded[0][1].endswith("r1.pdf")


async def test_execute_missing_file_raises_failed_before_submit(tmp_path):
    ex, session = executor(tmp_path)
    rec = record(fields=[{"selector": "#cv", "label": "CV", "value": "nope.pdf",
                          "source": "resume", "needs_you": False, "kind": "file"}])
    with pytest.raises(ExecutionFailed):
        await ex.execute(rec)
    assert session.submitted is False


async def test_execute_fill_error_raises_failed(tmp_path):
    ex, _ = executor(tmp_path, session=FakeSession(fail_fill=True))
    with pytest.raises(ExecutionFailed):
        await ex.execute(record())


async def test_execute_submit_error_raises_ambiguous(tmp_path):
    ex, _ = executor(tmp_path, session=FakeSession(fail_submit=True))
    with pytest.raises(ExecutionAmbiguous):
        await ex.execute(record())


async def test_execute_screenshot_failure_still_returns_success_with_note(tmp_path):
    ex, session = executor(tmp_path, session=FakeSession(fail_screenshot=True))
    updates = await ex.execute(record())
    assert updates.get("confirmation_screenshot") is None
    assert "screenshot failed" in updates["notes"]
    assert session.submitted is True


async def test_execute_uses_fresh_browser_session(tmp_path):
    ex, _ = executor(tmp_path)
    await ex.execute(record())
    assert ex._browser.reset_calls == 1


# ---------- tailor generator ----------


class FakePipeline:
    def __init__(self):
        self.calls = []

    async def tailor(self, job_key):
        self.calls.append(job_key)
        return {"ok": True, "rid": "r-new"}


async def test_tailor_generator_delegates_to_pipeline():
    pipe = FakePipeline()
    gen = TailorResumeGenerator(pipe)
    out = await gen.generate({"name": "job-hunt"}, {"key": "job-9"})
    assert out == {"ok": True, "rid": "r-new"}
    assert pipe.calls == ["job-9"]

import json

from switchgear.career.bank import load_bank
from switchgear.config import Settings
from switchgear.gateway import Completion
from switchgear.jobs.model import make_job
from switchgear.pdf import NullPdfRenderer
from switchgear.resume.pipeline import TailorPipeline
from switchgear.storage.memory import MemoryStorage
from switchgear.tools.tailor_resume import make_tailor_resume_tool


class FakeCompleteGateway:
    def __init__(self, completions):
        self._completions = list(completions)
        self.calls: list[dict] = []

    async def complete(self, tier, messages, tools=None):
        self.calls.append({"tier": tier, "messages": list(messages)})
        item = self._completions.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakePdfRenderer:
    def __init__(self, result_path=None):
        self._result_path = result_path
        self.calls: list[dict] = []

    async def render_pdf(self, html, out_path):
        self.calls.append({"html": html, "out_path": out_path})
        return self._result_path


def _bank(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "profile.yaml").write_text(
        "name: Alex Example\nemail: owner@example.com\nheadline: Software engineer\n"
        "summary: Builds reliable backend systems.\n"
    )
    (tmp_path / "skills.yaml").write_text(
        "skills:\n  - {name: Python, years: 5}\n  - {name: FastAPI, years: 3}\n"
    )
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "acme.yaml").write_text(
        "company: Acme Corp\ntitle: Senior Engineer\nstart: 2022-01\nend: present\n"
        "facts:\n"
        "  - id: cut-latency\n"
        '    text: "Cut checkout p99 latency 40% by rewriting the cart service"\n'
        "    skills: [python, performance]\n"
        '    metric: "40% p99 reduction"\n'
        "  - id: led-migration\n"
        '    text: "Led migration to a new billing platform"\n'
        "    skills: [python]\n"
    )
    return load_bank(str(tmp_path))


def _provider(bank):
    async def provider():
        return bank
    return provider


def _job(**kwargs):
    defaults = dict(
        url="https://boards.greenhouse.io/acme/jobs/1",
        title="Backend Engineer",
        company="Globex",
        description="We need a backend engineer with Python experience.",
        source="greenhouse",
    )
    defaults.update(kwargs)
    return make_job(**defaults)


def _selection_content(bullets=None):
    bullets = bullets if bullets is not None else [
        {"fact_id": "cut-latency", "text": None},
        {"fact_id": "led-migration", "text": "Led the migration to a new billing platform"},
    ]
    return json.dumps({
        "summary": "A concise, grounded summary.",
        "sections": [
            {
                "heading": "Experience",
                "entries": [
                    {
                        "company": "Acme Corp",
                        "title": "Senior Engineer",
                        "dates": "2022-01 - present",
                        "bullets": bullets,
                    }
                ],
            }
        ],
    })


def _settings(tmp_path, **overrides):
    return Settings(_env_file=None, state_dir=str(tmp_path / "state"), **overrides)


async def test_pipeline_happy_path_writes_html_and_stores_record(tmp_path):
    bank = _bank(tmp_path / "bank")
    storage = MemoryStorage()
    job = _job()
    await storage.put("jobs", job["key"], job)
    gateway = FakeCompleteGateway(
        [Completion(message={"content": _selection_content()}, usage=10)])
    pipeline = TailorPipeline(gateway, storage, _provider(bank), NullPdfRenderer(),
                              _settings(tmp_path))

    result = await pipeline.tailor(job["key"])

    assert result["ok"] is True
    assert result["job_key"] == job["key"]
    assert result["job_title"] == job["title"]
    assert result["company"] == job["company"]
    assert result["keyword_report"] == {"hit": ["Python"], "missed": []}
    assert result["selection"]["summary"] == "A concise, grounded summary."
    assert result["html_file"] == f"{result['rid']}.html"
    assert result["rid"].startswith(f"resume-{job['key'][:12]}-")

    html_path = tmp_path / "state" / "artifacts" / "resumes" / result["html_file"]
    assert html_path.is_file()
    assert "Alex Example" in html_path.read_text()

    stored = await storage.get("resumes", result["rid"])
    assert stored["rid"] == result["rid"]
    assert stored["keyword_report"] == result["keyword_report"]
    assert stored["selection"] == result["selection"]


async def test_pipeline_pdf_file_none_with_null_renderer(tmp_path):
    bank = _bank(tmp_path / "bank")
    storage = MemoryStorage()
    job = _job()
    await storage.put("jobs", job["key"], job)
    gateway = FakeCompleteGateway(
        [Completion(message={"content": _selection_content()}, usage=10)])
    pipeline = TailorPipeline(gateway, storage, _provider(bank), NullPdfRenderer(),
                              _settings(tmp_path))

    result = await pipeline.tailor(job["key"])

    assert result["pdf_file"] is None
    pdf_path = tmp_path / "state" / "artifacts" / "resumes" / f"{result['rid']}.pdf"
    assert not pdf_path.exists()


async def test_pipeline_pdf_file_set_with_fake_renderer(tmp_path):
    bank = _bank(tmp_path / "bank")
    storage = MemoryStorage()
    job = _job()
    await storage.put("jobs", job["key"], job)
    gateway = FakeCompleteGateway(
        [Completion(message={"content": _selection_content()}, usage=10)])
    settings = _settings(tmp_path)
    expected_pdf_path = str(
        tmp_path / "state" / "artifacts" / "resumes" / "placeholder.pdf"
    )
    renderer = FakePdfRenderer(result_path=expected_pdf_path)
    pipeline = TailorPipeline(gateway, storage, _provider(bank), renderer, settings)

    result = await pipeline.tailor(job["key"])

    assert result["pdf_file"] == f"{result['rid']}.pdf"
    assert renderer.calls[0]["out_path"] == str(
        tmp_path / "state" / "artifacts" / "resumes" / f"{result['rid']}.pdf")

    stored = await storage.get("resumes", result["rid"])
    assert stored["pdf_file"] == result["pdf_file"]


async def test_pipeline_job_not_found_returns_error(tmp_path):
    bank = _bank(tmp_path / "bank")
    storage = MemoryStorage()
    gateway = FakeCompleteGateway([])
    pipeline = TailorPipeline(gateway, storage, _provider(bank), NullPdfRenderer(),
                              _settings(tmp_path))

    result = await pipeline.tailor("missing-job-key")

    assert result == {"error": "job not found"}
    assert gateway.calls == []


async def test_pipeline_tailor_error_propagates_without_writing_artifact(tmp_path):
    bank = _bank(tmp_path / "bank")
    storage = MemoryStorage()
    job = _job()
    await storage.put("jobs", job["key"], job)
    bad_content = _selection_content(bullets=[{"fact_id": "invented-fact", "text": None}])
    gateway = FakeCompleteGateway(
        [Completion(message={"content": bad_content}, usage=10)])
    pipeline = TailorPipeline(gateway, storage, _provider(bank), NullPdfRenderer(),
                              _settings(tmp_path))

    result = await pipeline.tailor(job["key"])

    assert "error" in result
    assert "tailoring failed" in result["error"]
    assert "invented-fact" in result["error"]

    resumes_dir = tmp_path / "state" / "artifacts" / "resumes"
    assert not resumes_dir.exists() or list(resumes_dir.iterdir()) == []
    assert await storage.query("resumes") == []


async def test_pipeline_structurally_malformed_selection_returns_error(tmp_path):
    bank = _bank(tmp_path / "bank")
    storage = MemoryStorage()
    job = _job()
    await storage.put("jobs", job["key"], job)
    malformed_content = json.dumps({"summary": "A concise summary.", "sections": ["Experience"]})
    gateway = FakeCompleteGateway(
        [Completion(message={"content": malformed_content}, usage=10)])
    pipeline = TailorPipeline(gateway, storage, _provider(bank), NullPdfRenderer(),
                              _settings(tmp_path))

    result = await pipeline.tailor(job["key"])

    assert "error" in result
    assert result["error"].startswith("tailoring failed: ")

    resumes_dir = tmp_path / "state" / "artifacts" / "resumes"
    assert not resumes_dir.exists() or list(resumes_dir.iterdir()) == []
    assert await storage.query("resumes") == []


async def test_pipeline_errors_when_bank_unavailable(tmp_path):
    async def no_bank():
        return None

    storage = MemoryStorage()
    await storage.put("jobs", "job-x", {"key": "job-x", "title": "T"})
    gateway = FakeCompleteGateway([])
    pipeline = TailorPipeline(gateway, storage, no_bank, NullPdfRenderer(),
                              _settings(tmp_path))
    assert await pipeline.tailor("job-x") == {"error": "career bank unavailable"}
    assert gateway.calls == []
    assert await storage.query("resumes") == []


# ---------- make_tailor_resume_tool ----------


async def test_tailor_resume_tool_returns_summary_without_full_selection(tmp_path):
    bank = _bank(tmp_path / "bank")
    storage = MemoryStorage()
    job = _job()
    await storage.put("jobs", job["key"], job)
    gateway = FakeCompleteGateway(
        [Completion(message={"content": _selection_content()}, usage=10)])
    pipeline = TailorPipeline(gateway, storage, _provider(bank), NullPdfRenderer(),
                              _settings(tmp_path))
    tool = make_tailor_resume_tool(pipeline)

    result = await tool.handler(job_key=job["key"])

    assert tool.name == "tailor_resume"
    assert result["ok"] is True
    assert "selection" not in result
    assert result["job_title"] == job["title"]
    assert result["company"] == job["company"]
    assert result["bullets"] == 2
    assert result["rephrased"] == 1
    assert result["keyword_report"] == {"hit": ["Python"], "missed": []}
    assert result["files"]["html"].endswith(".html")


async def test_tailor_resume_tool_passes_through_errors(tmp_path):
    bank = _bank(tmp_path / "bank")
    storage = MemoryStorage()
    gateway = FakeCompleteGateway([])
    pipeline = TailorPipeline(gateway, storage, _provider(bank), NullPdfRenderer(),
                              _settings(tmp_path))
    tool = make_tailor_resume_tool(pipeline)

    result = await tool.handler(job_key="missing-job-key")

    assert result == {"error": "job not found"}

import httpx

from switchgear.auth import sign_session
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app

OWNER = "me@example.com"


def _bank_dir(tmp_path):
    bank_dir = tmp_path / "bank"
    bank_dir.mkdir()
    (bank_dir / "profile.yaml").write_text(
        "name: Alex Example\nemail: owner@example.com\nheadline: Software engineer\n"
        "summary: Builds reliable backend systems.\n"
    )
    (bank_dir / "skills.yaml").write_text(
        "skills:\n  - {name: Python, years: 5}\n"
    )
    exp_dir = bank_dir / "experience"
    exp_dir.mkdir()
    (exp_dir / "acme.yaml").write_text(
        "company: Acme Corp\ntitle: Senior Engineer\nstart: 2022-01\nend: present\n"
        "facts:\n"
        "  - id: cut-latency\n"
        '    text: "Cut checkout p99 latency 40% by rewriting the cart service"\n'
        "    skills: [python, performance]\n"
        '    metric: "40% p99 reduction"\n'
    )
    return bank_dir


def _settings(tmp_path, **overrides):
    overrides.setdefault("career_dir", str(_bank_dir(tmp_path)))
    overrides.setdefault("state_dir", str(tmp_path / "state"))
    return Settings(_env_file=None, owner_email=OWNER, session_secret="s3", **overrides)


def client(app):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(app.state.switchgear.settings, OWNER))
    return c


def make_app(tmp_path, **overrides):
    settings = _settings(tmp_path, **overrides)
    return create_app(settings=settings, storage=MemoryStorage())


# ---------- GET /screenshots/{filename} ----------


async def test_screenshot_file_download_roundtrip(tmp_path):
    app = make_app(tmp_path)
    shot_dir = app.state.switchgear.browser_manager.screenshot_dir
    (shot_dir / "shot1.png").write_bytes(b"fake-png-bytes")

    async with client(app) as c:
        r = await c.get("/screenshots/shot1.png")
    assert r.status_code == 200
    assert r.content == b"fake-png-bytes"


async def test_screenshot_file_missing_returns_404(tmp_path):
    app = make_app(tmp_path)
    async with client(app) as c:
        r = await c.get("/screenshots/does-not-exist.png")
    assert r.status_code == 404


async def test_screenshot_file_rejects_traversal(tmp_path):
    app = make_app(tmp_path)
    async with client(app) as c:
        r = await c.get("/screenshots/..foo")
    assert r.status_code == 400


async def test_screenshot_file_requires_auth(tmp_path):
    app = make_app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        r = await c.get("/screenshots/whatever.png")
    assert r.status_code == 401


# ---------- GET /resumes/{filename} ----------


async def test_resume_file_download_roundtrip(tmp_path):
    app = make_app(tmp_path)
    from switchgear.pdf import resume_artifact_dir
    d = resume_artifact_dir(app.state.switchgear.settings)
    (d / "r1.html").write_text("<html>resume</html>")
    async with client(app) as c:
        r = await c.get("/resumes/r1.html")
    assert r.status_code == 200
    assert "resume" in r.text


async def test_resume_file_rejects_traversal_and_missing(tmp_path):
    app = make_app(tmp_path)
    async with client(app) as c:
        assert (await c.get("/resumes/..evil")).status_code == 400
        assert (await c.get("/resumes/none.html")).status_code == 404

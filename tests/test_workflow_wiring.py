"""Integration coverage for workflow-layer wiring and definition seeding."""
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
    overrides.setdefault("state_dir", str(tmp_path / "state"))
    return Settings(_env_file=None, owner_email=OWNER, session_secret="s3", **overrides)


def make_app(tmp_path, **overrides):
    settings = _settings(tmp_path, **overrides)
    return create_app(settings=settings, storage=MemoryStorage())


async def test_wiring_registers_all_plugins_unconditionally(tmp_path):
    app = make_app(tmp_path, career_dir=str(tmp_path / "does-not-exist"))
    state = app.state.switchgear

    assert state.workflow_plugins.executor_names == {"submit-application", "send-digest",
                                                     "channel-send"}
    assert set(state.workflow_plugins.generator_names) == {"tailor-resume", "llm-brief"}
    assert state.gated_actions is not None
    assert state.workflow_store is not None
    assert state.tailor_pipeline is not None


async def test_seed_dir_seeds_only_core_repo_workflow_active(tmp_path):
    app = make_app(tmp_path, career_dir=str(tmp_path / "does-not-exist"))
    state = app.state.switchgear

    seeded = await state.workflow_store.seed_dir("workflows")
    assert seeded == 1
    doc = await state.workflow_store.get("channel-email")
    assert doc is not None
    assert doc["status"] == "active"


async def test_bank_provider_uses_career_dir_fallback(tmp_path):
    app = make_app(tmp_path, career_dir=str(_bank_dir(tmp_path)))
    bank = await app.state.switchgear.bank_provider()
    assert bank is not None
    assert bank.profile["name"] == "Alex Example"


async def test_bank_provider_none_when_no_bank_anywhere(tmp_path):
    app = make_app(tmp_path, career_dir=str(tmp_path / "does-not-exist"))
    assert await app.state.switchgear.bank_provider() is None


async def test_healthz_still_reachable_with_workflow_layer_wired(tmp_path):
    app = make_app(tmp_path, career_dir=str(_bank_dir(tmp_path)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        c.cookies.set("session", sign_session(app.state.switchgear.settings, OWNER))
        r = await c.get("/healthz")
    assert r.json() == {"ok": True}

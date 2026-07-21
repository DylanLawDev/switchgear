import httpx

from switchgear.config import Settings
from switchgear.auth import sign_session
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from tests.fakes import FakeGateway

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")


async def test_index_renders_chat_page():
    app = create_app(settings=S, gateway=FakeGateway([]))
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    async with c:
        r = await c.get("/")
        assert r.status_code == 200 and "chat.js" in r.text
        # message history endpoint
        assert (await c.get("/api/conversations/none")).json() == []


async def test_skills_page_renders():
    app = create_app(settings=S, gateway=FakeGateway([]))
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    async with c:
        r = await c.get("/skills")
    assert r.status_code == 200 and "skills.js" in r.text


PAGES = [("/", "chat"), ("/skills", "skills"), ("/resources", "resources"),
        ("/memories", "memories"), ("/channels/email", "channels")]


async def test_all_pages_share_header_with_active_tab():
    app = create_app(settings=S, gateway=FakeGateway([]))
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    async with c:
        for path, key in PAGES:
            r = await c.get(path)
            assert r.status_code == 200, path
            assert 'class="wordmark"' in r.text, path
            assert f'class="tab active" data-tab="{key}"' in r.text, path
            assert 'id="wire"' in r.text, path


async def test_resources_page_renders():
    app = create_app(settings=S, gateway=FakeGateway([]))
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    async with c:
        r = await c.get("/resources")
    assert r.status_code == 200 and "resources.js" in r.text


def make_app(tmp_path):
    settings = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3",
                        state_dir=str(tmp_path / "state"),
                        career_dir=str(tmp_path / "no-bank"))
    return create_app(settings=settings, gateway=FakeGateway([]), storage=MemoryStorage())


def client(app):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(app.state.switchgear.settings, "me@example.com"))
    return c


WORKFLOW_TEXT = """---
schema_version: 1
name: demo-flow
description: demo workflow
items:
  label: thing
  label_plural: things
  title_field: title
  fields:
    title: {type: text}
intake:
  skills: []
---
Demo body.
"""


async def seed_workflow(app):
    await app.state.switchgear.workflow_store.save(WORKFLOW_TEXT, source="repo")


async def test_workflow_page_renders_shell_and_embeds_definition(tmp_path):
    app = make_app(tmp_path)
    await seed_workflow(app)
    async with client(app) as c:
        r = await c.get("/workflows/demo-flow")
    assert r.status_code == 200
    assert 'id="wf-def"' in r.text
    assert '"title_field": "title"' in r.text
    assert "workflow.js" in r.text
    assert 'class="tab active" data-tab="wf:demo-flow"' in r.text


async def test_workflow_page_404s_for_unknown_or_inactive(tmp_path):
    app = make_app(tmp_path)
    await seed_workflow(app)
    await app.state.switchgear.workflow_store.set_status("demo-flow", "pending")
    async with client(app) as c:
        assert (await c.get("/workflows/demo-flow")).status_code == 404
        assert (await c.get("/workflows/never-existed")).status_code == 404


async def test_header_shows_workflow_tab_on_other_pages(tmp_path):
    app = make_app(tmp_path)
    await seed_workflow(app)
    async with client(app) as c:
        r = await c.get("/skills")
    assert 'data-tab="wf:demo-flow"' in r.text
    assert ">demo flow<" in r.text          # dash becomes space in the label

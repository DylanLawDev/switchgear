import httpx
from pathlib import Path

from switchgear.auth import sign_session
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from tests.fakes import FakeGateway

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")
SKILL = """---
name: queued-skill
description: Queue me
tools: [http_fetch]
---
Do the thing.
"""


def client(app):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, S.owner_email))
    return c


async def test_generic_api_approves_skill_without_preapproval_mutation():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    proposal = await app.state.switchgear.skill_writes.propose(SKILL)
    ref = proposal["approval"]
    assert await app.state.switchgear.skill_store.get("queued-skill") is None

    async with client(app) as c:
        pending = (await c.get(f"/api/approvals/{ref['kind']}/{ref['id']}")).json()
        assert pending["status"] == "pending"
        assert pending["title"] == "create skill queued-skill"
        approved = await c.post(f"/api/approvals/{ref['kind']}/{ref['id']}",
                                json={"action": "approve"})
        assert approved.status_code == 200

    assert (await app.state.switchgear.skill_store.get("queued-skill"))["status"] == "active"


async def test_generic_api_rejects_resource_proposal():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    proposal = await app.state.switchgear.resource_writes.propose(
        "create", "notes", kind="txt", content="draft")
    ref = proposal["approval"]

    async with client(app) as c:
        rejected = await c.post(f"/api/approvals/{ref['kind']}/{ref['id']}",
                                json={"action": "reject"})
        assert rejected.status_code == 200

    assert await app.state.switchgear.resource_store.get("notes") is None


async def test_generic_api_approves_workflow_action_with_context():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    await app.state.switchgear.workflow_store.save(
        Path("workflows/channel-email/WORKFLOW.md").read_text(), source="repo")
    wf = await app.state.switchgear.workflow_store.get("channel-email")
    key = "act-generic"
    await app.state.switchgear.storage.put(wf["actions"]["collection"], key, {
        wf["actions"]["key_field"]: key,
        wf["actions"]["item_ref_field"]: "message-1",
        "status": "draft", "fields": [], "notes": "",
        "created_at": 9_999_999_999, "updated_at": 9_999_999_999,
        "executed_at": None,
    })

    async with client(app) as c:
        pending = (await c.get(
            f"/api/approvals/workflow_action/{key}?context=channel-email")).json()
        assert pending["status"] == "pending"
        approved = await c.post(f"/api/approvals/workflow_action/{key}", json={
            "action": "approve", "context": "channel-email"})
        assert approved.status_code == 200

    record = await app.state.switchgear.gated_actions.get(wf, key)
    assert record["status"] == "approved"

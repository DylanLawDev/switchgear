from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.tools.base import use_origin
from switchgear.web.app import create_app
from tests.fakes import FakeGateway


SKILL = """---
name: queued-guide
description: Queued guidance
tools: []
---
Follow the guide.
"""


async def test_background_approvals_are_immediate_but_chat_waits_for_escalation():
    settings = Settings(_env_file=None, approval_chat_escalation_seconds=900)
    app = create_app(settings=settings, gateway=FakeGateway([]), storage=MemoryStorage())
    await app.state.switchgear.skill_writes.propose(SKILL)
    assert await app.state.switchgear.approvals.list() == []

    with use_origin("workflow"):
        background = await app.state.switchgear.skill_writes.propose(
            SKILL.replace("queued-guide", "background-guide"))
    listed = await app.state.switchgear.approvals.list()
    assert [row["id"] for row in listed] == [background["id"]]
    assert listed[0]["origin"] == "workflow"


async def test_zero_delay_escalates_chat_approval_to_inbox():
    settings = Settings(_env_file=None, approval_chat_escalation_seconds=0)
    app = create_app(settings=settings, gateway=FakeGateway([]), storage=MemoryStorage())
    proposal = await app.state.switchgear.skill_writes.propose(SKILL)
    assert [row["id"] for row in await app.state.switchgear.approvals.list()] == [proposal["id"]]

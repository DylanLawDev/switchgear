import pytest

from switchgear.config import Settings
from switchgear.email.sender import ConsoleEmailSender
from switchgear.storage.memory import MemoryStorage
from switchgear.workflows.actions import ExecutionAmbiguous, ExecutionFailed
from switchgear.workflows.plugins.digest import SendDigestExecutor

OWNER = "me@example.com"
ITEM = {"key": "itm-abc", "title": "Agents in prod"}


def make(email_sender=None, storage=None):
    storage = storage or MemoryStorage()
    return SendDigestExecutor(
        storage, email_sender or ConsoleEmailSender(),
        Settings(_env_file=None, owner_email=OWNER),
        artifacts_collection="wf-research-artifacts",
        item_ref_field="item_key"), storage


async def seed_brief(storage, body="## Brief\n- a point", created_at=1.0):
    key = f"brief-{created_at}"
    await storage.put("wf-research-artifacts", key, {
        "key": key, "item_key": "itm-abc", "title": "Brief",
        "body": body, "created_at": created_at})


async def test_draft_composes_email_from_briefs_newest_first():
    ex, storage = make()
    await seed_brief(storage, body="old brief", created_at=1.0)
    await seed_brief(storage, body="new brief", created_at=2.0)
    result = await ex.draft(dict(ITEM))
    values = {f["selector"]: f for f in result.fields}
    assert values["to"]["value"] == OWNER
    assert values["subject"]["value"] == "Research digest — Agents in prod"
    assert values["body"]["value"].index("new brief") < values["body"]["value"].index("old brief")
    assert values["body"]["needs_you"] is False
    assert values["to"]["kind"] == "text"
    assert values["subject"]["kind"] == "text"
    assert values["body"]["kind"] == "multiline"


async def test_draft_with_no_briefs_flags_needs_you():
    ex, _ = make()
    result = await ex.draft(dict(ITEM))
    body = next(f for f in result.fields if f["selector"] == "body")
    assert body["needs_you"] is True
    assert "generate" in result.notes


def record(**overrides):
    rec = {"key": "act-1", "item_key": "itm-abc", "status": "executing",
           "fields": [
               {"selector": "to", "label": "To", "value": OWNER,
                "source": "profile", "needs_you": False, "kind": "text"},
               {"selector": "subject", "label": "Subject", "value": "Digest",
                "source": "agent", "needs_you": False, "kind": "text"},
               {"selector": "body", "label": "Body", "value": "**hi** <script>",
                "source": "agent", "needs_you": False, "kind": "text"}]}
    rec.update(overrides)
    return rec


async def test_execute_sends_escaped_html():
    sender = ConsoleEmailSender()
    ex, _ = make(email_sender=sender)
    out = await ex.execute(record())
    assert out == {}
    assert sender.sent[0]["to"] == OWNER
    assert sender.sent[0]["subject"] == "Digest"
    assert "&lt;script&gt;" in sender.sent[0]["html"]
    assert "<script>" not in sender.sent[0]["html"]


async def test_execute_missing_values_fails_before_send():
    sender = ConsoleEmailSender()
    ex, _ = make(email_sender=sender)
    rec = record()
    rec["fields"] = [f for f in rec["fields"] if f["selector"] != "body"]
    with pytest.raises(ExecutionFailed):
        await ex.execute(rec)
    assert sender.sent == []


async def test_execute_send_error_is_ambiguous():
    class BoomSender(ConsoleEmailSender):
        async def send(self, to, subject, html):
            raise TimeoutError("gateway timeout")

    ex, _ = make(email_sender=BoomSender())
    with pytest.raises(ExecutionAmbiguous):
        await ex.execute(record())

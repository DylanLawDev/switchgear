import hashlib

from switchgear.channels.ingest import ChannelIngest, message_key, sanitize_body
from switchgear.channels.model import parse_channel
from switchgear.channels.transport import ConsoleTransport
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.workflows.store import WorkflowStore

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")

WF = """---
schema_version: 1
name: channel-email
description: Inbound messages on the agent's email channel
items:
  label: message
  label_plural: messages
  title_field: subject
  fields:
    subject:         {type: text}
    sender:          {type: text}
    to:              {type: text}
    thread_id:       {type: text}
    provider_id:     {type: text}
    rfc_message_id:  {type: text}
    body_text:       {type: markdown}
    received_at:     {type: timestamp}
    triage_route:    {type: enum}
    triage_reason:   {type: text}
    triage_status:   {type: status}
  list_fields: [subject, sender, triage_status, triage_route, received_at]
  sort: [-received_at]
intake:
  skills: []
---
Body.
"""

CHANNEL = """---
schema_version: 1
name: email
transport: console
workflow: channel-email
poll_interval: 5m
triage:
  tier: bulk
  routes:
    file: {}
    workflow_item:
      workflows: [job-hunt, research]
    draft_reply: {tier: writing}
---
Email channel.
"""


# ---------- sanitize_body ----------


def test_sanitize_strips_invisible_unicode():
    hidden = "he​ll‌o‍ w﻿or­ld"
    assert sanitize_body(hidden, False, 100) == "hello world"


def test_sanitize_html_drops_tags_scripts_and_styles():
    html = ("<html><style>.h{display:none}</style><body><p>Real text</p>"
            "<script>alert(1)</script>"
            '<div style="display:none">formerly hidden</div></body></html>')
    out = sanitize_body(html, True, 1000)
    assert "Real text" in out
    assert "alert" not in out
    assert "display:none" not in out       # style block contents dropped
    assert "formerly hidden" in out        # CSS-hiding stripped => visible


def test_sanitize_unescapes_entities_after_tag_strip():
    assert sanitize_body("<p>a &amp; b</p>", True, 100) == "a & b"


def test_sanitize_plain_text_is_not_html_processed():
    assert sanitize_body("2 < 3 and &amp; stays", False, 100) == "2 < 3 and &amp; stays"


def test_sanitize_collapses_whitespace_runs():
    assert sanitize_body("a  \t b\n\n\n\n\nc", False, 100) == "a b\n\nc"


def test_sanitize_truncates_with_marker():
    out = sanitize_body("x" * 50, False, 10)
    assert out == "x" * 10 + "\n[truncated]"


def test_sanitize_handles_none_and_empty():
    assert sanitize_body("", False, 100) == ""
    assert sanitize_body(None, False, 100) == ""


# ---------- message_key ----------


def test_message_key_is_deterministic_and_prefixed():
    k = message_key("gmail-abc123")
    assert k == message_key("gmail-abc123")
    assert k == "msg-" + hashlib.sha256(b"gmail-abc123").hexdigest()[:16]
    assert message_key("other") != k


# ---------- ChannelIngest.poll ----------


async def make_ingest(triage=None, settings=S):
    storage = MemoryStorage()
    wf_store = WorkflowStore(storage, generators=set(), executors=set())
    await wf_store.save(WF, source="repo")
    transport = ConsoleTransport()
    channel = parse_channel(CHANNEL)
    ingest = ChannelIngest(channel, transport, wf_store, storage, settings,
                           triage=triage)
    return ingest, transport, storage, wf_store


def msg(pid="m1", body="hello", is_html=False, **kw):
    return {"provider_id": pid, "thread_id": f"t-{pid}",
            "sender": "alice@example.com", "to": "agent@example.com",
            "subject": f"Subject {pid}", "body": body, "body_is_html": is_html,
            "received_at": 1720000000.0, "rfc_message_id": f"<{pid}@example.com>",
            **kw}


async def test_poll_stores_sanitized_items_and_advances_cursor():
    ingest, transport, storage, _ = await make_ingest()
    transport.append_inbound(msg("m1", body="he​llo <b>world</b>",
                                 is_html=True))
    out = await ingest.poll()
    assert out == {"fetched": 1, "stored": 1, "duplicates": 0, "failed": 0}
    key = message_key("m1")
    doc = await storage.get("wf-channel-email-items", key)
    assert doc["subject"] == "Subject m1"
    assert doc["sender"] == "alice@example.com"
    assert doc["to"] == "agent@example.com"
    assert doc["thread_id"] == "t-m1"
    assert doc["provider_id"] == "m1"
    assert doc["rfc_message_id"] == "<m1@example.com>"
    assert doc["body_text"] == "hello world"       # sanitized BEFORE storage
    assert doc["received_at"] == 1720000000.0
    assert doc["triage_status"] == "pending"
    assert doc["triage_route"] is None
    assert doc["triage_reason"] is None
    assert doc["key"] == key
    state = await storage.get("channel-state", "email")
    assert state["cursor"] == "1"
    assert state["last_poll"] is not None       # status route reads this key


async def test_poll_stores_none_when_transport_omits_rfc_message_id():
    ingest, transport, storage, _ = await make_ingest()
    m = msg("m1")
    del m["rfc_message_id"]
    transport.append_inbound(m)
    await ingest.poll()
    doc = await storage.get("wf-channel-email-items", message_key("m1"))
    assert doc["rfc_message_id"] is None


async def test_repoll_fetches_nothing_new():
    ingest, transport, _, _ = await make_ingest()
    transport.append_inbound(msg("m1"))
    await ingest.poll()
    assert await ingest.poll() == {"fetched": 0, "stored": 0, "duplicates": 0,
                                   "failed": 0}


async def test_redelivered_message_is_deduped_by_key():
    ingest, transport, storage, _ = await make_ingest()
    transport.append_inbound(msg("m1"))
    await ingest.poll()
    transport.append_inbound(msg("m1", body="redelivered copy"))
    out = await ingest.poll()
    assert out == {"fetched": 1, "stored": 0, "duplicates": 1, "failed": 0}
    doc = await storage.get("wf-channel-email-items", message_key("m1"))
    assert doc["body_text"] == "hello"             # original kept


async def test_duplicate_within_one_batch_counted():
    ingest, transport, _, _ = await make_ingest()
    transport.append_inbound(msg("m1"))
    transport.append_inbound(msg("m1"))
    out = await ingest.poll()
    assert out == {"fetched": 2, "stored": 1, "duplicates": 1, "failed": 0}


async def test_poll_audits_one_record():
    ingest, transport, storage, _ = await make_ingest()
    transport.append_inbound(msg("m1"))
    transport.append_inbound(msg("m2"))
    await ingest.poll()
    audits = [a for a in await storage.query("audit")
              if a["action"] == "channel_poll"]
    assert len(audits) == 1
    assert audits[0]["name"] == "email"
    assert audits[0]["fetched"] == 2
    assert audits[0]["stored"] == 2
    assert audits[0]["failed"] == 0
    assert isinstance(audits[0]["at"], float)


async def test_poll_skips_inactive_workflow_without_advancing_cursor():
    ingest, transport, storage, wf_store = await make_ingest()
    transport.append_inbound(msg("m1"))
    await wf_store.set_status("channel-email", "disabled")
    assert await ingest.poll() == {"fetched": 0, "stored": 0, "duplicates": 0,
                                   "failed": 0}
    assert await storage.get("channel-state", "email") is None
    assert await storage.get("wf-channel-email-items", message_key("m1")) is None


async def test_poll_truncates_oversize_bodies_before_storage():
    small = Settings(_env_file=None, owner_email="me@example.com",
                     session_secret="s3", channel_body_max_chars=10)
    ingest, transport, storage, _ = await make_ingest(settings=small)
    transport.append_inbound(msg("m1", body="y" * 50))
    await ingest.poll()
    doc = await storage.get("wf-channel-email-items", message_key("m1"))
    assert doc["body_text"] == "y" * 10 + "\n[truncated]"


async def test_poll_stamps_received_at_when_transport_omits_it():
    ingest, transport, storage, _ = await make_ingest()
    m = msg("m1")
    m["received_at"] = None
    transport.append_inbound(m)
    await ingest.poll()
    doc = await storage.get("wf-channel-email-items", message_key("m1"))
    assert isinstance(doc["received_at"], float)   # save_item stamps timestamps


# ---------- failed-message accounting ----------

WF_MISSING_FIELD = """---
schema_version: 1
name: channel-email
description: Inbound messages on the agent's email channel (missing a field)
items:
  label: message
  label_plural: messages
  title_field: subject
  fields:
    subject:         {type: text}
    sender:          {type: text}
    to:              {type: text}
    thread_id:       {type: text}
    provider_id:     {type: text}
    rfc_message_id:  {type: text}
    body_text:       {type: markdown}
    received_at:     {type: timestamp}
    triage_route:    {type: enum}
    triage_status:   {type: status}
  list_fields: [subject, sender, triage_status, triage_route, received_at]
  sort: [-received_at]
intake:
  skills: []
---
Body.
"""


async def test_poll_counts_save_item_validation_failures():
    # The workflow declares only 9 of the 10 keys the ingest item builds
    # (triage_reason is missing), so save_item rejects every item with an
    # "unknown fields" error instead of "new".
    storage = MemoryStorage()
    wf_store = WorkflowStore(storage, generators=set(), executors=set())
    await wf_store.save(WF_MISSING_FIELD, source="repo")
    transport = ConsoleTransport()
    channel = parse_channel(CHANNEL)
    ingest = ChannelIngest(channel, transport, wf_store, storage, S)
    transport.append_inbound(msg("m1"))

    out = await ingest.poll()

    assert out == {"fetched": 1, "stored": 0, "duplicates": 0, "failed": 1}
    assert await storage.get("wf-channel-email-items", message_key("m1")) is None
    state = await storage.get("channel-state", "email")
    assert state["cursor"] == "1"                  # cursor still advances
    audits = [a for a in await storage.query("audit")
              if a["action"] == "channel_poll"]
    assert audits[0]["failed"] == 1


class RecordingTriage:
    def __init__(self, fail=False):
        self.seen = []
        self._fail = fail

    async def triage_message(self, doc):
        self.seen.append(doc)
        if self._fail:
            raise RuntimeError("classifier down")


async def test_poll_invokes_triage_once_per_stored_message():
    triage = RecordingTriage()
    ingest, transport, _, _ = await make_ingest(triage=triage)
    transport.append_inbound(msg("m1"))
    transport.append_inbound(msg("m1"))            # duplicate: no triage call
    await ingest.poll()
    assert [d["provider_id"] for d in triage.seen] == ["m1"]
    assert triage.seen[0]["triage_status"] == "pending"
    assert triage.seen[0]["body_text"] == "hello"  # triage sees sanitized text


async def test_triage_failure_never_breaks_poll():
    triage = RecordingTriage(fail=True)
    ingest, transport, storage, _ = await make_ingest(triage=triage)
    transport.append_inbound(msg("m1"))
    out = await ingest.poll()
    assert out["stored"] == 1
    assert await storage.get("wf-channel-email-items",
                             message_key("m1")) is not None
    assert (await storage.get("channel-state", "email"))["cursor"] == "1"

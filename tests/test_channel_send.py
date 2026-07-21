import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from switchgear.channels.send import (
    RATE_COLLECTION,
    SUPPRESSION_COLLECTION,
    ChannelSendError,
    ChannelSendService,
    extract_address,
)
from switchgear.channels.sendfns import SendFunctionStore
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.workflows.actions import ExecutionFailed, GatedActionService
from switchgear.workflows.model import parse_workflow
from switchgear.workflows.plugins.channel_send import ChannelSendExecutor
from switchgear.workflows.registry import WorkflowPlugins
from switchgear.workflows.store import WorkflowStore

WF_TEXT = Path("workflows/channel-email/WORKFLOW.md").read_text()
CHANNEL = {"name": "email", "workflow": "channel-email",
           "address": "agent@example.com"}
OWNER = "me@example.com"


class Clock:
    def __init__(self, now=1_700_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class RecordingTransport:
    """Implements the ChannelTransport send surface. The service depends only
    on the call signature, so tests pin exact arguments here instead of
    relying on ConsoleTransport's internal .sent entry shape."""

    def __init__(self, fail_with=None):
        self.sent = []
        self.fail_with = fail_with

    async def send(self, to, subject, body_text, in_reply_to=None):
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append({"to": to, "subject": subject, "body": body_text,
                          "in_reply_to": in_reply_to})


@dataclass
class Env:
    service: ChannelSendService
    storage: MemoryStorage
    sendfns: SendFunctionStore
    transport: RecordingTransport
    gated: GatedActionService
    executor: ChannelSendExecutor
    wf: dict
    clock: Clock


async def make_env(transport=None, clock=None, storage=None) -> Env:
    storage = storage or MemoryStorage()
    settings = Settings(_env_file=None, owner_email=OWNER)
    clock = clock or Clock()
    transport = transport or RecordingTransport()
    sendfns = SendFunctionStore(storage, settings)
    plugins = WorkflowPlugins()
    executor = ChannelSendExecutor(None)
    plugins.register_executor("channel-send", executor)
    workflows = WorkflowStore(storage, generators=set(),
                              executors=plugins.executor_names)
    wf = await workflows.save(WF_TEXT, source="repo")
    gated = GatedActionService(storage, plugins, settings, clock=clock)
    service = ChannelSendService(storage, transport, sendfns, workflows,
                                 gated, CHANNEL, settings, clock=clock)
    executor.send_service = service
    return Env(service, storage, sendfns, transport, gated, executor, wf, clock)


async def seed_message(env: Env, key="msg-abc",
                       sender="Jane Doe <Jane@Corp.com>", provider_id="prov-1",
                       rfc_message_id="<rfc-1@corp.com>"):
    await env.storage.put(env.wf["items"]["collection"], key, {
        "key": key, "subject": "Hello there", "sender": sender,
        "to": "agent@example.com", "thread_id": "t-1",
        "provider_id": provider_id, "rfc_message_id": rfc_message_id,
        "body_text": "hi", "received_at": 1000.0,
        "triage_route": "file", "triage_reason": "", "triage_status": "routed"})


OWNER_PING = {
    "name": "owner-ping", "description": "notify the owner",
    "params": {"topic": {"type": "string", "max_chars": 120}},
    "subject_template": "Ping: {{topic}}",
    "body_template": "Topic {{topic}} noted on {{date}}.",
    "recipient_rule": {"type": "owner"}, "gate": "auto",
}

ACK = {
    "name": "ack", "description": "acknowledge a message", "params": {},
    "subject_template": "Re: got it",
    "body_template": "Thanks {{sender}}, received on {{date}}.",
    "recipient_rule": {"type": "reply_to_thread"}, "gate": "auto",
}

OUTREACH = {
    "name": "outreach", "description": "cold outreach",
    "params": {"role": {"type": "string", "max_chars": 120}},
    "subject_template": "Regarding the {{role}} role",
    "body_template": "Hello,\n\nI am interested in the {{role}} role.",
    "recipient_rule": {"type": "fixed", "address": "vip@corp.com"},
    "gate": "approve",
}

PICKY = {
    "name": "picky", "description": "allowlist outreach",
    "params": {"company": {"type": "enum", "values": ["stripe", "anthropic"]}},
    "subject_template": "Hello {{company}}",
    "body_template": "Hi {{company}} team.",
    "recipient_rule": {"type": "allowlist",
                       "addresses": ["a@stripe.com", "b@anthropic.com"]},
    "gate": "approve",
}


# ---------- definition + helpers ----------


def test_channel_workflow_defines_send_actions():
    wf = parse_workflow(WF_TEXT, generators=set(), executors={"channel-send"})
    actions = wf["actions"]
    assert actions["executor"] == "channel-send"
    assert actions["label"] == "send" and actions["label_plural"] == "sends"
    assert actions["approval_ttl"] == 3 * 86400
    assert actions["draft_ttl"] == 14 * 86400


def test_extract_address():
    assert extract_address("Jane Doe <Jane@Corp.com>") == "jane@corp.com"
    assert extract_address("jane@corp.com") == "jane@corp.com"
    assert extract_address("  BOB@X.IO  ") == "bob@x.io"
    assert extract_address("total junk") is None
    assert extract_address("") is None


# ---------- steps 1-2: function + params ----------


async def test_unknown_and_disabled_functions_rejected():
    env = await make_env()
    with pytest.raises(ChannelSendError):
        await env.service.send("nope", {}, actor="agent")
    await env.sendfns.save({**OWNER_PING, "enabled": False})
    with pytest.raises(ChannelSendError):
        await env.service.send("owner-ping", {"topic": "x"}, actor="agent")


async def test_param_validation_matrix():
    env = await make_env()
    await env.sendfns.save(dict(OWNER_PING))
    with pytest.raises(ChannelSendError):   # unknown param
        await env.service.send("owner-ping", {"topic": "x", "evil": "y"},
                               actor="agent")
    with pytest.raises(ChannelSendError):   # missing param
        await env.service.send("owner-ping", {}, actor="agent")
    with pytest.raises(ChannelSendError):   # over max_chars
        await env.service.send("owner-ping", {"topic": "x" * 121}, actor="agent")
    with pytest.raises(ChannelSendError):   # wrong type
        await env.service.send("owner-ping", {"topic": 42}, actor="agent")


async def test_number_and_enum_params():
    env = await make_env()
    await env.sendfns.save({
        "name": "num", "description": "number param",
        "params": {"n": {"type": "number"}},
        "subject_template": "n={{n}}", "body_template": "value {{n}}",
        "recipient_rule": {"type": "owner"}, "gate": "auto"})
    with pytest.raises(ChannelSendError):
        await env.service.send("num", {"n": True}, actor="agent")
    with pytest.raises(ChannelSendError):
        await env.service.send("num", {"n": "3"}, actor="agent")
    out = await env.service.send("num", {"n": 3}, actor="agent")
    assert out["status"] == "sent"
    assert env.transport.sent[0]["subject"] == "n=3"

    await env.sendfns.save({**PICKY, "gate": "approve"})
    with pytest.raises(ChannelSendError):
        await env.service.send("picky", {"company": "google",
                                         "to": "a@stripe.com"}, actor="agent")


async def test_param_values_are_crlf_stripped():
    env = await make_env()
    await env.sendfns.save(dict(OWNER_PING))
    await env.service.send("owner-ping", {"topic": "evil\r\nBcc: x@y.com"},
                           actor="agent")
    subject = env.transport.sent[0]["subject"]
    assert "\r" not in subject and "\n" not in subject
    assert "Bcc" in subject  # content kept, line break neutralized


async def test_to_param_only_accepted_for_allowlist():
    env = await make_env()
    await env.sendfns.save(dict(OWNER_PING))
    with pytest.raises(ChannelSendError):
        await env.service.send("owner-ping",
                               {"topic": "x", "to": "attacker@evil.com"},
                               actor="agent")


async def test_tampered_auto_cold_doc_is_refused_at_send_time():
    # written around the store: the service re-asserts the structural rule
    env = await make_env()
    await env.storage.put("send-functions", "evil", {
        "name": "evil", "description": "tampered", "params": {},
        "subject_template": "x", "body_template": "y",
        "recipient_rule": {"type": "fixed", "address": "attacker@evil.com"},
        "gate": "auto", "rate_limit_per_day": 5, "enabled": True})
    with pytest.raises(ChannelSendError):
        await env.service.send("evil", {}, actor="agent")
    assert env.transport.sent == []


# ---------- step 3: render ----------


async def test_sender_slot_requires_a_source_message():
    env = await make_env()
    await env.sendfns.save(dict(ACK))
    with pytest.raises(ChannelSendError):
        await env.service.send("ack", {}, actor="agent")  # no message key


async def test_param_value_cannot_smuggle_a_placeholder():
    env = await make_env()
    await env.sendfns.save(dict(OWNER_PING))
    with pytest.raises(ChannelSendError):
        await env.service.send("owner-ping", {"topic": "{{date}}"},
                               actor="agent")
    assert env.transport.sent == []


# ---------- step 4: recipients (auto rules) ----------


async def test_owner_rule_sends_to_owner_email():
    env = await make_env()
    await env.sendfns.save(dict(OWNER_PING))
    out = await env.service.send("owner-ping", {"topic": "hi"}, actor="agent")
    assert out == {"status": "sent", "to": OWNER}
    sent = env.transport.sent[0]
    assert sent["to"] == OWNER and sent["in_reply_to"] is None
    assert sent["subject"] == "Ping: hi"
    assert "2023-11-14" in sent["body"]  # {{date}} from the pinned clock


async def test_owner_rule_without_owner_email_errors():
    env = await make_env()
    env.service._s = Settings(_env_file=None, owner_email="")
    await env.sendfns.save(dict(OWNER_PING))
    with pytest.raises(ChannelSendError):
        await env.service.send("owner-ping", {"topic": "hi"}, actor="agent")


async def test_reply_rule_derives_counterparty_and_threads():
    env = await make_env()
    await seed_message(env)
    await env.sendfns.save(dict(ACK))
    out = await env.service.send("ack", {}, actor="agent",
                                 source_message_key="msg-abc")
    assert out == {"status": "sent", "to": "jane@corp.com"}
    sent = env.transport.sent[0]
    assert sent["in_reply_to"] == "<rfc-1@corp.com>"
    assert "jane@corp.com" in sent["body"]  # {{sender}} = extracted address


async def test_reply_rule_missing_message_errors():
    env = await make_env()
    await env.sendfns.save(dict(ACK))
    with pytest.raises(ChannelSendError):
        await env.service.send("ack", {}, actor="agent",
                               source_message_key="msg-gone")


async def test_reply_threads_on_rfc_message_id_not_internal_provider_id():
    # provider_id is Gmail's internal id; GmailTransport writes in_reply_to
    # verbatim into the RFC In-Reply-To/References headers, which require
    # the RFC Message-ID. Using provider_id there sends unthreaded mail even
    # though the caller reports success.
    env = await make_env()
    await seed_message(env, provider_id="internal-999",
                       rfc_message_id="<abc@mail>")
    await env.sendfns.save(dict(ACK))
    await env.service.send("ack", {}, actor="agent",
                           source_message_key="msg-abc")
    sent = env.transport.sent[0]
    assert sent["in_reply_to"] == "<abc@mail>"
    assert sent["in_reply_to"] != "internal-999"


async def test_reply_with_no_rfc_message_id_sends_unthreaded():
    # ConsoleTransport messages, or any stored message that lacked a
    # Message-ID header, have rfc_message_id=None. Falling back to
    # provider_id there would put a garbage internal id in the headers;
    # unthreaded is the honest fallback.
    env = await make_env()
    await seed_message(env, rfc_message_id=None)
    await env.sendfns.save(dict(ACK))
    out = await env.service.send("ack", {}, actor="agent",
                                 source_message_key="msg-abc")
    assert out == {"status": "sent", "to": "jane@corp.com"}
    sent = env.transport.sent[0]
    assert sent["in_reply_to"] is None


# ---------- step 4b: suppression ----------


async def test_suppression_blocks_case_insensitively_and_audits():
    env = await make_env()
    await env.sendfns.save(dict(OWNER_PING))
    await env.storage.put(SUPPRESSION_COLLECTION, OWNER,
                          {"address": OWNER, "added_at": 0})
    with pytest.raises(ChannelSendError):
        await env.service.send("owner-ping", {"topic": "hi"}, actor="agent")
    assert env.transport.sent == []
    rejected = await env.storage.query(
        "audit", where={"tool": "channel-send-rejected"})
    assert rejected[0]["reason"] == "suppressed"
    assert rejected[0]["recipient"] == OWNER


# ---------- step 5: rate limits ----------


async def test_rate_limit_zero_means_no_sends():
    env = await make_env()
    await env.sendfns.save({**OWNER_PING, "rate_limit_per_day": 0})
    with pytest.raises(ChannelSendError):
        await env.service.send("owner-ping", {"topic": "hi"}, actor="agent")
    rejected = await env.storage.query(
        "audit", where={"tool": "channel-send-rejected"})
    assert rejected[0]["reason"] == "rate-limited"


async def test_rate_limit_counts_transmissions_and_rolls_over_utc_days():
    env = await make_env()
    await env.sendfns.save({**OWNER_PING, "rate_limit_per_day": 2})
    for _ in range(2):
        await env.service.send("owner-ping", {"topic": "hi"}, actor="agent")
    with pytest.raises(ChannelSendError):
        await env.service.send("owner-ping", {"topic": "hi"}, actor="agent")
    env.clock.now += 86400  # next UTC day, fresh counter key
    out = await env.service.send("owner-ping", {"topic": "hi"}, actor="agent")
    assert out["status"] == "sent"
    assert len(env.transport.sent) == 3


# ---------- step 8: audit shape ----------


async def test_send_audit_shape_and_new_recipient_flag():
    env = await make_env()
    await env.sendfns.save(dict(OWNER_PING))
    await env.service.send("owner-ping", {"topic": "one"}, actor="agent")
    await env.service.send("owner-ping", {"topic": "two"}, actor="agent")
    audits = await env.storage.query("audit", where={"tool": "channel-send"})
    audits.sort(key=lambda a: a["at"])
    first = {k: v for k, v in audits[0].items() if k != "_id"}
    assert set(first) == {"tool", "function", "recipient", "gate", "actor",
                          "new_recipient", "at"}
    assert first["function"] == "owner-ping" and first["gate"] == "auto"
    assert first["actor"] == "agent" and first["recipient"] == OWNER
    assert audits[0]["new_recipient"] is True
    assert audits[1]["new_recipient"] is False


async def test_rejections_do_not_mark_a_recipient_as_seen():
    env = await make_env()
    await env.sendfns.save({**OWNER_PING, "rate_limit_per_day": 0})
    with pytest.raises(ChannelSendError):
        await env.service.send("owner-ping", {"topic": "x"}, actor="agent")
    await env.sendfns.save({**OWNER_PING, "name": "owner-ping2"})
    await env.service.send("owner-ping2", {"topic": "x"}, actor="agent")
    sends = await env.storage.query("audit", where={"tool": "channel-send"})
    assert sends[0]["new_recipient"] is True


# ---------- step 6: gate approve — draft creation ----------


async def test_cold_send_creates_synthetic_item_and_materialized_draft():
    env = await make_env()
    await env.sendfns.save(dict(OUTREACH))
    out = await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    assert out["status"] == "pending_approval"
    assert env.transport.sent == []  # nothing sent before approval

    record = await env.gated.get(env.wf, out["key"])
    values = {f["selector"]: f["value"] for f in record["fields"]}
    assert values["function"] == "outreach"
    assert values["to"] == "vip@corp.com"
    assert values["subject"] == "Regarding the SRE role"
    assert "SRE role" in values["body"]
    assert record["function"] == "outreach"
    assert record["params"] == {"role": "SRE"}
    assert record["source_message_key"] is None

    item_key = record[env.wf["actions"]["item_ref_field"]]
    assert item_key.startswith("out-")
    item = await env.storage.get(env.wf["items"]["collection"], item_key)
    assert item["sender"] == "agent"
    assert item["triage_status"] == "outbound"


async def test_reply_approve_send_drafts_against_the_source_message():
    env = await make_env()
    await seed_message(env)
    await env.sendfns.save({**ACK, "name": "ack-gated", "gate": "approve"})
    out = await env.service.send("ack-gated", {}, actor="agent",
                                 source_message_key="msg-abc")
    record = await env.gated.get(env.wf, out["key"])
    assert record[env.wf["actions"]["item_ref_field"]] == "msg-abc"
    assert record["source_message_key"] == "msg-abc"


async def test_reply_approve_execute_threads_on_rfc_message_id():
    env = await make_env()
    await seed_message(env, provider_id="internal-999",
                       rfc_message_id="<abc@mail>")
    await env.sendfns.save({**ACK, "name": "ack-gated", "gate": "approve"})
    out = await env.service.send("ack-gated", {}, actor="agent",
                                 source_message_key="msg-abc")
    await approve(env, out["key"])
    record = await env.gated.execute(env.wf, out["key"])
    assert record["status"] == "executed"
    sent = env.transport.sent[0]
    assert sent["in_reply_to"] == "<abc@mail>"


async def test_allowlist_send_requires_and_checks_to_param():
    env = await make_env()
    await env.sendfns.save(dict(PICKY))
    with pytest.raises(ChannelSendError):    # to required
        await env.service.send("picky", {"company": "stripe"}, actor="agent")
    with pytest.raises(ChannelSendError):    # not on the list
        await env.service.send("picky", {"company": "stripe",
                                         "to": "other@corp.com"}, actor="agent")
    out = await env.service.send("picky", {"company": "stripe",
                                           "to": "A@Stripe.com"}, actor="agent")
    assert out["status"] == "pending_approval"
    record = await env.gated.get(env.wf, out["key"])
    values = {f["selector"]: f["value"] for f in record["fields"]}
    assert values["to"] == "a@stripe.com"    # normalized


async def test_ui_started_draft_without_prepared_payload_errors():
    env = await make_env()
    await seed_message(env)
    record = await env.gated.start_draft(env.wf, "msg-abc")
    assert record["fields"] == []
    assert "no prepared send" in record["notes"] or "no prepared send" in str(
        record.get("error"))


async def test_unbound_executor_fails_safe():
    env = await make_env()
    env.executor.send_service = None
    await seed_message(env)
    record = await env.gated.start_draft(env.wf, "msg-abc")
    assert record["fields"] == []
    with pytest.raises(ExecutionFailed):
        await env.executor.execute({"fields": []})


# ---------- gate approve — execution ----------


async def approve(env: Env, key: str):
    return await env.gated.approve(env.wf, key, approved_by=OWNER)


async def test_approved_cold_send_executes_and_audits():
    env = await make_env()
    await env.sendfns.save(dict(OUTREACH))
    out = await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    await approve(env, out["key"])
    record = await env.gated.execute(env.wf, out["key"])
    assert record["status"] == "executed"
    assert record["sent_to"] == "vip@corp.com"
    sent = env.transport.sent[0]
    assert sent["to"] == "vip@corp.com"
    assert sent["subject"] == "Regarding the SRE role"
    audits = await env.storage.query("audit", where={"tool": "channel-send"})
    assert audits[0]["gate"] == "approve" and audits[0]["actor"] == "owner"


async def test_owner_edited_body_wins_at_execution():
    env = await make_env()
    await env.sendfns.save(dict(OUTREACH))
    out = await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    await env.gated.update_fields(env.wf, out["key"], [
        {"selector": "body", "value": "Owner-edited body.", "needs_you": False}])
    await approve(env, out["key"])
    record = await env.gated.execute(env.wf, out["key"])
    assert record["status"] == "executed"
    assert env.transport.sent[0]["body"] == "Owner-edited body."


async def test_edited_to_field_cannot_escape_the_rule():
    env = await make_env()
    await env.sendfns.save(dict(OUTREACH))
    out = await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    await env.gated.update_fields(env.wf, out["key"], [
        {"selector": "to", "value": "attacker@evil.com", "needs_you": False}])
    await approve(env, out["key"])
    record = await env.gated.execute(env.wf, out["key"])
    assert record["status"] == "failed"
    assert env.transport.sent == []


async def test_execute_recheck_disabled_function_fails_safely():
    env = await make_env()
    await env.sendfns.save(dict(OUTREACH))
    out = await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    await approve(env, out["key"])
    await env.sendfns.save({**OUTREACH, "enabled": False})
    record = await env.gated.execute(env.wf, out["key"])
    assert record["status"] == "failed"
    assert env.transport.sent == []


async def test_execute_recheck_suppression_added_after_approval():
    env = await make_env()
    await env.sendfns.save(dict(OUTREACH))
    out = await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    await approve(env, out["key"])
    await env.storage.put(SUPPRESSION_COLLECTION, "vip@corp.com",
                          {"address": "vip@corp.com", "added_at": 0})
    record = await env.gated.execute(env.wf, out["key"])
    assert record["status"] == "failed"
    assert env.transport.sent == []


async def test_execute_recheck_recipient_drift_fails():
    env = await make_env()
    await env.sendfns.save(dict(OUTREACH))
    out = await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    await approve(env, out["key"])
    await env.sendfns.save({**OUTREACH,
                            "recipient_rule": {"type": "fixed",
                                               "address": "new@corp.com"}})
    record = await env.gated.execute(env.wf, out["key"])
    assert record["status"] == "failed"
    assert env.transport.sent == []


async def test_pending_drafts_do_not_consume_rate_budget():
    env = await make_env()
    await env.sendfns.save({**OUTREACH, "rate_limit_per_day": 1})
    first = await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    second = await env.service.send("outreach", {"role": "SWE"}, actor="agent")
    assert first["status"] == second["status"] == "pending_approval"
    await approve(env, first["key"])
    await approve(env, second["key"])
    assert (await env.gated.execute(env.wf, first["key"]))["status"] == "executed"
    record = await env.gated.execute(env.wf, second["key"])
    assert record["status"] == "failed"          # execute-time rate re-check
    assert len(env.transport.sent) == 1


# ---------- built-in reply drafts (function: None — the Phase 3 seam) ----------


def test_reply_rate_setting_default():
    assert Settings(_env_file=None).channel_reply_rate_per_day == 20


async def seed_reply_draft(env: Env, message_key="msg-abc", key="act-reply1",
                           to="jane@corp.com"):
    """Materialize a reply draft the way Phase 3's draft_reply route will:
    written directly into the actions collection, function None, canonical
    source_message_key persisted, code-set to/subject + drafted body."""
    now = env.clock()
    await env.storage.put(env.wf["actions"]["collection"], key, {
        "key": key, "item_key": message_key, "status": "draft",
        "function": None, "params": {}, "source_message_key": message_key,
        "fields": [
            {"selector": "to", "label": "To", "value": to, "source": "rule",
             "needs_you": False, "kind": "text"},
            {"selector": "subject", "label": "Subject",
             "value": "Re: Hello there", "source": "rule",
             "needs_you": False, "kind": "text"},
            {"selector": "body", "label": "Body (text/plain)",
             "value": "Thanks, noted.", "source": "agent",
             "needs_you": False, "kind": "multiline"},
        ],
        "notes": "", "created_at": now, "updated_at": now,
        "executed_at": None})
    return key


async def test_builtin_reply_executes_with_derived_recipient_and_threading():
    env = await make_env()
    await seed_message(env)
    key = await seed_reply_draft(env)
    await approve(env, key)
    record = await env.gated.execute(env.wf, key)
    assert record["status"] == "executed"
    assert record["sent_to"] == "jane@corp.com"
    sent = env.transport.sent[0]
    assert sent["to"] == "jane@corp.com"       # derived from source sender
    assert sent["in_reply_to"] == "<rfc-1@corp.com>"  # threading headers set
    assert sent["subject"] == "Re: Hello there"
    assert sent["body"] == "Thanks, noted."    # approved hash-pinned body
    audits = await env.storage.query("audit", where={"tool": "channel-send"})
    assert audits[0]["function"] is None       # contract shape, function None
    assert audits[0]["gate"] == "approve" and audits[0]["actor"] == "owner"
    assert audits[0]["recipient"] == "jane@corp.com"


async def test_builtin_reply_falls_back_to_item_ref_when_key_missing():
    env = await make_env()
    await seed_message(env)
    key = await seed_reply_draft(env)
    coll = env.wf["actions"]["collection"]
    stored = await env.storage.get(coll, key)
    stored.pop("source_message_key")           # only the item ref remains
    await env.storage.put(coll, key, stored)
    await approve(env, key)
    record = await env.gated.execute(env.wf, key)
    assert record["status"] == "executed"
    assert env.transport.sent[0]["to"] == "jane@corp.com"


async def test_builtin_reply_missing_source_message_fails_safely():
    env = await make_env()
    key = await seed_reply_draft(env, message_key="msg-gone")
    await approve(env, key)
    record = await env.gated.execute(env.wf, key)
    assert record["status"] == "failed"        # ExecutionFailed, no side effect
    assert env.transport.sent == []


async def test_builtin_reply_suppressed_sender_fails():
    env = await make_env()
    await seed_message(env)
    key = await seed_reply_draft(env)
    await approve(env, key)
    await env.storage.put(SUPPRESSION_COLLECTION, "jane@corp.com",
                          {"address": "jane@corp.com", "added_at": 0})
    record = await env.gated.execute(env.wf, key)
    assert record["status"] == "failed"
    assert env.transport.sent == []
    rejected = await env.storage.query(
        "audit", where={"tool": "channel-send-rejected"})
    assert rejected[0]["reason"] == "suppressed"
    assert rejected[0]["function"] is None


async def test_builtin_reply_edited_to_cannot_escape_the_sender():
    env = await make_env()
    await seed_message(env)
    key = await seed_reply_draft(env, to="attacker@evil.com")
    await approve(env, key)
    record = await env.gated.execute(env.wf, key)
    assert record["status"] == "failed"
    assert env.transport.sent == []


async def test_builtin_reply_global_rate_ceiling():
    env = await make_env()
    env.service._s = Settings(_env_file=None, owner_email=OWNER,
                              channel_reply_rate_per_day=1)
    await seed_message(env, key="msg-aaa", provider_id="p-a")
    await seed_message(env, key="msg-bbb", provider_id="p-b")
    k1 = await seed_reply_draft(env, message_key="msg-aaa", key="act-r1")
    k2 = await seed_reply_draft(env, message_key="msg-bbb", key="act-r2")
    await approve(env, k1)
    await approve(env, k2)
    assert (await env.gated.execute(env.wf, k1))["status"] == "executed"
    record = await env.gated.execute(env.wf, k2)
    assert record["status"] == "failed"        # builtin-reply-<day> exhausted
    assert len(env.transport.sent) == 1


async def test_transport_failure_during_execute_is_ambiguous():
    env = await make_env(transport=RecordingTransport(
        fail_with=RuntimeError("smtp died")))
    await env.sendfns.save(dict(OUTREACH))
    out = await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    await approve(env, out["key"])
    record = await env.gated.execute(env.wf, out["key"])
    assert record["status"] == "possibly_executed"


async def test_transport_failure_during_auto_send_propagates():
    env = await make_env(transport=RecordingTransport(
        fail_with=RuntimeError("smtp died")))
    await env.sendfns.save(dict(OWNER_PING))
    with pytest.raises(RuntimeError):
        await env.service.send("owner-ping", {"topic": "hi"}, actor="agent")


async def test_approval_expires_after_three_days():
    env = await make_env()
    await env.sendfns.save(dict(OUTREACH))
    out = await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    await approve(env, out["key"])
    env.clock.now += 3 * 86400 + 1
    assert await env.gated.execute(env.wf, out["key"]) == {
        "error": "send not approved"}


# ---------- review fixes: concurrency + error boundaries + reserved name ----


class SlowRateReadStorage(MemoryStorage):
    """Widens the read window on the rate counter so two concurrent sends
    deterministically interleave at the read-check-increment."""

    async def get(self, collection, key):
        if collection == RATE_COLLECTION:
            await asyncio.sleep(0.01)
        return await super().get(collection, key)


class RateWriteFailsStorage(MemoryStorage):
    async def put(self, collection, key, doc):
        if collection == RATE_COLLECTION:
            raise RuntimeError("firestore hiccup")
        return await super().put(collection, key, doc)


def reply_record(message_key, to="jane@corp.com"):
    return {"function": None, "params": {}, "source_message_key": message_key,
            "fields": [
                {"selector": "to", "value": to},
                {"selector": "subject", "value": "Re: Hello there"},
                {"selector": "body", "value": "Thanks."}]}


async def test_concurrent_sends_cannot_race_past_the_rate_ceiling():
    env = await make_env(storage=SlowRateReadStorage())
    env.service._s = Settings(_env_file=None, owner_email=OWNER,
                              channel_reply_rate_per_day=1)
    await seed_message(env, key="msg-aaa", provider_id="p-a")
    await seed_message(env, key="msg-bbb", provider_id="p-b")
    results = await asyncio.gather(
        env.service.execute_prepared(reply_record("msg-aaa")),
        env.service.execute_prepared(reply_record("msg-bbb")),
        return_exceptions=True)
    oks = [r for r in results if isinstance(r, dict)]
    errs = [r for r in results if isinstance(r, ChannelSendError)]
    assert len(oks) == 1 and len(errs) == 1, results
    assert len(env.transport.sent) == 1        # exactly one transmission
    day = time.strftime("%Y%m%d", time.gmtime(env.clock()))
    counter = await env.storage.get(RATE_COLLECTION, f"builtin-reply-{day}")
    assert counter["count"] == 1               # no lost increment
    rejected = await env.storage.query(
        "audit", where={"tool": "channel-send-rejected"})
    assert rejected[0]["reason"] == "rate-limited"


async def test_external_start_draft_steals_the_prepared_payload_safely():
    """Documents the accepted prepared-handoff race (losing-side contract):
    an external gated.start_draft for the same item while the payload is
    staged pops it first. The stolen draft is fully policy-derived (safe),
    pop-once means the payload lands on at most one draft (never a duplicate
    send), and the losing send() fails with a clean visible error."""
    env = await make_env()
    await env.sendfns.save(dict(OUTREACH))

    real_start_draft = env.gated.start_draft
    stolen = {}

    async def thief_wins_then_service_runs(wf, item_key):
        # the external workflow-UI call lands first, while staged
        stolen["record"] = await real_start_draft(wf, item_key)
        return await real_start_draft(wf, item_key)

    env.gated.start_draft = thief_wins_then_service_runs
    with pytest.raises(ChannelSendError, match="no prepared send"):
        await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    env.gated.start_draft = real_start_draft

    assert env.transport.sent == []            # nothing transmitted
    values = {f["selector"]: f["value"] for f in stolen["record"]["fields"]}
    assert values["to"] == "vip@corp.com"      # thief got the derived payload
    assert values["subject"] == "Regarding the SRE role"
    drafts = await env.storage.query(env.wf["actions"]["collection"])
    materialized = [d for d in drafts if d.get("fields")]
    assert len(materialized) == 1              # payload on exactly one draft
    assert env.service._prepared == {}         # nothing left staged


async def test_storage_failure_before_transport_is_failed_not_ambiguous():
    env = await make_env(storage=RateWriteFailsStorage())
    await env.sendfns.save(dict(OUTREACH))
    out = await env.service.send("outreach", {"role": "SRE"}, actor="agent")
    await approve(env, out["key"])
    record = await env.gated.execute(env.wf, out["key"])
    assert record["status"] == "failed"        # retryable, NOT ambiguous
    assert env.transport.sent == []


async def test_reserved_builtin_reply_name_is_refused_at_send_time():
    env = await make_env()
    # written around the store: save() rejects reserved names, so tamper
    await env.storage.put("send-functions", "builtin-reply", {
        "name": "builtin-reply", "description": "tampered", "params": {},
        "subject_template": "x", "body_template": "y",
        "recipient_rule": {"type": "owner"}, "gate": "auto",
        "rate_limit_per_day": 999, "enabled": True})
    with pytest.raises(ChannelSendError):
        await env.service.send("builtin-reply", {}, actor="agent")
    assert env.transport.sent == []

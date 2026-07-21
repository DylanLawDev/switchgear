import json

from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.tools import build_registry
from switchgear.tools.channel_tools import (
    make_channel_messages_tool,
    make_channel_send_tool,
)
from tests.fakes import FakeGateway
from tests.test_channel_send import ACK, OUTREACH, OWNER_PING, make_env, seed_message


# ---------- channel_send ----------


async def test_channel_send_schema():
    env = await make_env()
    tool = make_channel_send_tool(env.service)
    assert tool.name == "channel_send"
    assert tool.parameters["required"] == ["function"]
    assert tool.parameters["properties"]["params"]["type"] == "object"
    desc = tool.description.lower()
    assert "message_key" in desc  # how replies are addressed


async def test_channel_send_auto_and_pending_and_error():
    env = await make_env()
    await env.sendfns.save(dict(OWNER_PING))
    await env.sendfns.save(dict(OUTREACH))
    tool = make_channel_send_tool(env.service)
    sent = json.loads(await tool.handler(function="owner-ping",
                                         params={"topic": "hi"}))
    assert sent == {"status": "sent", "to": "me@example.com"}
    pending = json.loads(await tool.handler(function="outreach",
                                            params={"role": "SRE"}))
    assert pending["status"] == "pending_approval" and pending["key"]
    assert pending["approval"] == {
        "kind": "workflow_action", "id": pending["key"], "context": "channel-email"}
    error = json.loads(await tool.handler(function="nope", params={}))
    assert "error" in error


async def test_channel_send_hides_internal_errors():
    class ExplodingService:
        async def send(self, function, params, actor):
            raise RuntimeError("secret internal detail")

    tool = make_channel_send_tool(ExplodingService())
    out = json.loads(await tool.handler(function="owner-ping", params={}))
    assert out == {"error": "internal send failure"}
    assert "secret" not in json.dumps(out)


async def test_channel_send_reply_via_message_key_param():
    env = await make_env()
    await seed_message(env)
    await env.sendfns.save(dict(ACK))
    tool = make_channel_send_tool(env.service)
    out = json.loads(await tool.handler(
        function="ack", params={"message_key": "msg-abc"}))
    assert out == {"status": "sent", "to": "jane@corp.com"}
    # threading uses the RFC Message-ID, not Gmail's internal provider_id
    assert env.transport.sent[0]["in_reply_to"] == "<rfc-1@corp.com>"


# ---------- channel_messages ----------


async def test_channel_messages_list_filters_projects_caps_and_sorts():
    env = await make_env()
    for i in range(55):
        await seed_message(env, key=f"msg-{i:03d}", provider_id=f"p{i}")
        item = await env.storage.get(env.wf["items"]["collection"],
                                     f"msg-{i:03d}")
        item["received_at"] = 1000.0 + i
        await env.storage.put(env.wf["items"]["collection"], f"msg-{i:03d}",
                              item)
    await env.storage.put(env.wf["items"]["collection"], "out-123", {
        "key": "out-123", "subject": "outbound", "sender": "agent",
        "received_at": 9e9, "triage_status": "outbound"})
    tool = make_channel_messages_tool(env.service._workflows, env.storage)
    assert tool.name == "channel_messages"
    rows = json.loads(await tool.handler(op="list"))
    assert len(rows) == 50                       # capped
    assert rows[0]["key"] == "msg-054"           # newest first
    assert all(r["key"].startswith("msg-") for r in rows)
    assert set(rows[0]) == {"key", "subject", "sender", "received_at",
                            "triage_status"}


async def test_channel_messages_read_returns_declared_fields_only():
    env = await make_env()
    await seed_message(env)
    item = await env.storage.get(env.wf["items"]["collection"], "msg-abc")
    item["raw_mime"] = "SHOULD NEVER LEAVE STORAGE"
    await env.storage.put(env.wf["items"]["collection"], "msg-abc", item)
    tool = make_channel_messages_tool(env.service._workflows, env.storage)
    doc = json.loads(await tool.handler(op="read", key="msg-abc"))
    assert doc["body_text"] == "hi"
    assert "raw_mime" not in doc
    assert "error" in json.loads(await tool.handler(op="read", key="msg-x"))
    assert "error" in json.loads(await tool.handler(op="read"))
    assert "error" in json.loads(await tool.handler(op="explode"))


async def test_channel_messages_read_refuses_non_msg_keys():
    env = await make_env()
    await env.storage.put(env.wf["items"]["collection"], "out-123", {
        "key": "out-123", "subject": "outbound draft", "sender": "agent",
        "body_text": "pending outbound body", "received_at": 2000.0,
        "triage_status": "outbound"})
    tool = make_channel_messages_tool(env.service._workflows, env.storage)
    # An out-* item that EXISTS in the collection must be indistinguishable
    # from a missing document — no oracle for synthetic outbound items.
    out = json.loads(await tool.handler(op="read", key="out-123"))
    assert out == {"error": "message not found"}
    arbitrary = json.loads(await tool.handler(op="read", key="whatever-1"))
    assert arbitrary == {"error": "message not found"}


async def test_channel_messages_missing_workflow_errors():
    env = await make_env()

    class EmptyStore:
        async def get(self, name):
            return None

    tool = make_channel_messages_tool(EmptyStore(), env.storage)
    assert "error" in json.loads(await tool.handler(op="list"))


# ---------- registry wiring ----------


async def test_build_registry_registers_channel_tools_when_present():
    env = await make_env()
    settings = Settings(_env_file=None)
    reg = build_registry(settings, MemoryStorage(), FakeGateway([]),
                         channel_send_service=env.service,
                         workflow_store=env.service._workflows)
    assert "channel_send" in reg._tools
    assert "channel_messages" in reg._tools
    assert list(reg._tools)[-1] == "spawn_subagent"  # stays last


def test_build_registry_omits_channel_tools_by_default():
    reg = build_registry(Settings(_env_file=None), MemoryStorage(),
                         FakeGateway([]))
    assert "channel_send" not in reg._tools
    assert "channel_messages" not in reg._tools

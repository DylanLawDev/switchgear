import pytest

from switchgear.channels.model import (
    ChannelParseError,
    ChannelStore,
    parse_channel,
    poll_cron,
    validate_channel_refs,
)
from switchgear.storage.memory import MemoryStorage
from switchgear.workflows.store import WorkflowStore

VALID = """---
schema_version: 1
name: email
transport: console
workflow: channel-email
address: agent@example.com
poll_interval: 5m
triage:
  tier: bulk
  routes:
    file: {}
    workflow_item:
      workflows: [job-hunt, research]
    draft_reply: {tier: writing}
    auto_ack: {send_function: ack-receipt}
---
The agent's email channel.
"""


# ---------- parse_channel: valid shape ----------


def test_parse_valid_channel_full_shape():
    doc = parse_channel(VALID)
    assert doc["schema_version"] == 1
    assert doc["name"] == "email"
    assert doc["transport"] == "console"
    assert doc["workflow"] == "channel-email"
    assert doc["address"] == "agent@example.com"
    assert doc["poll_interval"] == 300.0
    assert doc["triage"]["tier"] == "bulk"
    assert set(doc["triage"]["routes"]) == {"file", "workflow_item",
                                            "draft_reply", "auto_ack"}
    assert doc["triage"]["routes"]["file"] == {}
    assert doc["triage"]["routes"]["workflow_item"] == {
        "workflows": ["job-hunt", "research"]}
    assert doc["triage"]["routes"]["draft_reply"] == {"tier": "writing"}
    assert doc["triage"]["routes"]["auto_ack"] == {"send_function": "ack-receipt"}
    assert doc["body"].startswith("The agent's email channel.")


def test_address_is_optional_and_defaults_none():
    doc = parse_channel(VALID.replace("address: agent@example.com\n", ""))
    assert doc["address"] is None


def test_minimal_routes_file_only():
    text = VALID
    for line in ("    workflow_item:\n      workflows: [job-hunt, research]\n",
                 "    draft_reply: {tier: writing}\n",
                 "    auto_ack: {send_function: ack-receipt}\n"):
        text = text.replace(line, "")
    doc = parse_channel(text)
    assert doc["triage"]["routes"] == {"file": {}}


# ---------- parse_channel: validation matrix ----------


def test_missing_frontmatter():
    with pytest.raises(ChannelParseError, match="frontmatter"):
        parse_channel("no frontmatter here")


def test_unterminated_frontmatter():
    with pytest.raises(ChannelParseError, match="frontmatter"):
        parse_channel("---\nname: email\n")


def test_bad_yaml():
    with pytest.raises(ChannelParseError, match="yaml"):
        parse_channel("---\n: [\n---\nx")


def test_schema_version_must_be_1():
    with pytest.raises(ChannelParseError, match="schema_version"):
        parse_channel(VALID.replace("schema_version: 1", "schema_version: 2"))


def test_invalid_name():
    with pytest.raises(ChannelParseError, match="name"):
        parse_channel(VALID.replace("name: email", "name: Bad Name"))


def test_unknown_transport():
    with pytest.raises(ChannelParseError, match="transport"):
        parse_channel(VALID.replace("transport: console", "transport: sms"))


def test_workflow_required():
    with pytest.raises(ChannelParseError, match="workflow"):
        parse_channel(VALID.replace("workflow: channel-email\n", ""))


def test_poll_interval_required_and_validated():
    with pytest.raises(ChannelParseError, match="poll_interval"):
        parse_channel(VALID.replace("poll_interval: 5m\n", ""))
    with pytest.raises(ChannelParseError, match="poll_interval"):
        parse_channel(VALID.replace("poll_interval: 5m", "poll_interval: soonish"))


def test_poll_interval_rejects_cron_unrepresentable_value():
    with pytest.raises(ChannelParseError, match="poll_interval"):
        parse_channel(VALID.replace("poll_interval: 5m", "poll_interval: 90m"))


def test_triage_block_required():
    with pytest.raises(ChannelParseError, match="triage"):
        parse_channel(VALID.split("triage:")[0] + "---\nBody.\n")


def test_triage_tier_enum():
    with pytest.raises(ChannelParseError, match="tier"):
        parse_channel(VALID.replace("tier: bulk", "tier: turbo"))


def test_unknown_route_rejected():
    with pytest.raises(ChannelParseError, match="unknown route"):
        parse_channel(VALID.replace("    file: {}",
                                    "    file: {}\n    forward_all: {}"))


def test_route_file_required():
    with pytest.raises(ChannelParseError, match="file"):
        parse_channel(VALID.replace("    file: {}\n", ""))


def test_workflow_item_requires_nonempty_valid_workflow_list():
    with pytest.raises(ChannelParseError, match="workflow_item"):
        parse_channel(VALID.replace("workflows: [job-hunt, research]",
                                    "workflows: []"))
    with pytest.raises(ChannelParseError, match="workflow_item"):
        parse_channel(VALID.replace("workflows: [job-hunt, research]",
                                    "workflows: [Bad Name]"))


def test_draft_reply_requires_tier():
    with pytest.raises(ChannelParseError, match="draft_reply"):
        parse_channel(VALID.replace("draft_reply: {tier: writing}",
                                    "draft_reply: {}"))


def test_auto_ack_requires_send_function():
    with pytest.raises(ChannelParseError, match="auto_ack"):
        parse_channel(VALID.replace("auto_ack: {send_function: ack-receipt}",
                                    "auto_ack: {}"))


# ---------- poll_cron ----------


def test_poll_cron_mapping():
    assert poll_cron(300.0) == "*/5 * * * *"      # 5m
    assert poll_cron(60.0) == "*/1 * * * *"       # 1m
    assert poll_cron(3600.0) == "0 */1 * * *"     # 1h
    assert poll_cron(21600.0) == "0 */6 * * *"    # 6h
    assert poll_cron(172800.0) == "0 0 */2 * *"   # 2d


def test_poll_cron_rejects_non_positive_or_sub_minute_intervals():
    with pytest.raises(ValueError):
        poll_cron(0.0)
    with pytest.raises(ValueError):
        poll_cron(-60.0)


def test_poll_cron_rejects_intervals_it_cannot_represent_faithfully():
    # 90m floors to hourly under the old (buggy) implementation — that's a
    # silently wrong cadence, so it must now raise instead.
    with pytest.raises(ValueError):
        poll_cron(5400.0)          # 90m
    with pytest.raises(ValueError):
        poll_cron(7 * 60.0)        # 7m: doesn't evenly divide 60
    with pytest.raises(ValueError):
        poll_cron(5 * 3600.0)      # 5h: doesn't evenly divide 24
    with pytest.raises(ValueError):
        poll_cron(90000.0)         # 25h: not a whole number of days


# ---------- ChannelStore ----------


BROKEN = VALID.replace("schema_version: 1", "schema_version: 9")


async def test_store_save_repo_source_is_active_and_get_roundtrips():
    s = ChannelStore(MemoryStorage())
    saved = await s.save(VALID, source="repo")
    assert saved["status"] == "active"
    got = await s.get("email")
    assert got["workflow"] == "channel-email"
    assert got["poll_interval"] == 300.0
    assert got["text"] == VALID
    assert got["source"] == "repo"


async def test_store_save_agent_source_is_pending():
    s = ChannelStore(MemoryStorage())
    assert (await s.save(VALID, source="agent"))["status"] == "pending"


async def test_store_save_rejects_invalid_definition():
    s = ChannelStore(MemoryStorage())
    with pytest.raises(ChannelParseError):
        await s.save(BROKEN, source="repo")
    assert await s.get("email") is None


async def test_store_list_returns_summaries_sorted():
    s = ChannelStore(MemoryStorage())
    await s.save(VALID, source="repo")
    assert await s.list() == [{"name": "email", "transport": "console",
                               "workflow": "channel-email", "status": "active",
                               "source": "repo"}]


async def test_store_set_status():
    s = ChannelStore(MemoryStorage())
    await s.save(VALID, source="agent")
    assert (await s.set_status("email", "active"))["status"] == "active"
    assert await s.set_status("missing", "active") is None


async def test_seed_dir_loads_valid_and_skips_invalid(tmp_path):
    (tmp_path / "email").mkdir()
    (tmp_path / "email" / "CHANNEL.md").write_text(VALID)
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "CHANNEL.md").write_text(BROKEN)
    s = ChannelStore(MemoryStorage())
    assert await s.seed_dir(str(tmp_path)) == 1
    assert (await s.get("email"))["status"] == "active"


async def test_seed_dir_missing_path_returns_zero():
    assert await ChannelStore(MemoryStorage()).seed_dir("/does/not/exist") == 0


async def test_seed_dir_is_idempotent(tmp_path):
    (tmp_path / "email").mkdir()
    (tmp_path / "email" / "CHANNEL.md").write_text(VALID)
    s = ChannelStore(MemoryStorage())
    assert await s.seed_dir(str(tmp_path)) == 1
    assert await s.seed_dir(str(tmp_path)) == 0


async def test_seed_dir_refreshes_changed_repo_def_preserving_status(tmp_path):
    (tmp_path / "email").mkdir()
    f = tmp_path / "email" / "CHANNEL.md"
    f.write_text(VALID)
    s = ChannelStore(MemoryStorage())
    await s.seed_dir(str(tmp_path))
    await s.set_status("email", "disabled")
    f.write_text(VALID.replace("poll_interval: 5m", "poll_interval: 10m"))
    assert await s.seed_dir(str(tmp_path)) == 1
    doc = await s.get("email")
    assert doc["poll_interval"] == 600.0
    assert doc["status"] == "disabled"
    assert doc["source"] == "repo"


async def test_seed_dir_never_overwrites_non_repo_sourced_channel(tmp_path):
    (tmp_path / "email").mkdir()
    (tmp_path / "email" / "CHANNEL.md").write_text(
        VALID.replace("poll_interval: 5m", "poll_interval: 10m"))
    s = ChannelStore(MemoryStorage())
    await s.save(VALID, source="agent")
    assert await s.seed_dir(str(tmp_path)) == 0
    doc = await s.get("email")
    assert doc["poll_interval"] == 300.0
    assert doc["source"] == "agent"


# ---------- validate_channel_refs ----------


MINIMAL_WF = """---
schema_version: 1
name: channel-email
description: messages
items:
  label: message
  label_plural: messages
  title_field: subject
  fields:
    subject: {type: text}
---
Body.
"""


def _wf(name):
    return MINIMAL_WF.replace("name: channel-email", f"name: {name}")


def _wf_store():
    return WorkflowStore(MemoryStorage(), generators=set(), executors=set())


async def test_refs_clean_channel_passes_and_none_skips_send_functions():
    wf = _wf_store()
    for n in ("channel-email", "job-hunt", "research"):
        await wf.save(_wf(n), source="repo")
    channel = parse_channel(VALID)
    assert await validate_channel_refs(channel, workflow_store=wf) == []


async def test_refs_flag_missing_then_inactive_workflow():
    wf = _wf_store()
    channel = parse_channel(VALID)
    problems = await validate_channel_refs(channel, workflow_store=wf)
    assert any("channel-email" in p and "not found" in p for p in problems)
    await wf.save(_wf("channel-email"), source="agent")  # pending, not active
    problems = await validate_channel_refs(channel, workflow_store=wf)
    assert any("channel-email" in p and "not active" in p for p in problems)


async def test_refs_flag_missing_workflow_item_targets():
    wf = _wf_store()
    await wf.save(_wf("channel-email"), source="repo")
    await wf.save(_wf("job-hunt"), source="repo")   # research missing
    channel = parse_channel(VALID)
    problems = await validate_channel_refs(channel, workflow_store=wf)
    assert problems == ["workflow_item target 'research' not found"]


async def test_refs_auto_ack_checked_only_when_names_supplied():
    wf = _wf_store()
    for n in ("channel-email", "job-hunt", "research"):
        await wf.save(_wf(n), source="repo")
    channel = parse_channel(VALID)
    assert await validate_channel_refs(
        channel, workflow_store=wf, send_function_names=None) == []
    problems = await validate_channel_refs(
        channel, workflow_store=wf, send_function_names=set())
    assert problems == ["auto_ack send function 'ack-receipt' not found"]
    assert await validate_channel_refs(
        channel, workflow_store=wf, send_function_names={"ack-receipt"}) == []


async def test_refs_never_raise_on_empty_channel_dict():
    problems = await validate_channel_refs(
        {}, workflow_store=_wf_store(), send_function_names=None)
    assert any("workflow" in p for p in problems)


async def test_refs_never_raise_when_triage_missing():
    wf = _wf_store()
    await wf.save(_wf("channel-email"), source="repo")
    problems = await validate_channel_refs(
        {"workflow": "channel-email"}, workflow_store=wf)
    assert problems == []


async def test_refs_never_raise_on_auto_ack_without_send_function():
    wf = _wf_store()
    await wf.save(_wf("channel-email"), source="repo")
    channel = {"workflow": "channel-email",
               "triage": {"routes": {"file": {}, "auto_ack": {}}}}
    assert await validate_channel_refs(
        channel, workflow_store=wf, send_function_names=None) == []
    problems = await validate_channel_refs(
        channel, workflow_store=wf, send_function_names={"ack-receipt"})
    assert len(problems) == 1
    assert "auto_ack" in problems[0]


# ---------- auto_ack structural rule (email channel phase 3) ----------


async def test_auto_ack_send_function_must_be_gate_auto_reply_to_thread():
    wf = _wf_store()
    await wf.save(_wf("channel-email"), source="repo")
    channel = {"workflow": "channel-email",
               "triage": {"routes": {"file": {},
                                     "auto_ack": {"send_function": "ack-receipt"}}}}
    fns = {"ack-receipt": {"name": "ack-receipt", "gate": "approve",
                           "recipient_rule": {"type": "allowlist",
                                              "addresses": ["a@b.example"]}}}
    problems = await validate_channel_refs(
        channel, workflow_store=wf,
        send_function_names=set(fns), send_functions=fns)
    assert any("gate:auto" in p and "ack-receipt" in p for p in problems)


async def test_auto_ack_gate_auto_reply_to_thread_yields_no_problems():
    wf = _wf_store()
    await wf.save(_wf("channel-email"), source="repo")
    channel = {"workflow": "channel-email",
               "triage": {"routes": {"file": {},
                                     "auto_ack": {"send_function": "ack-receipt"}}}}
    fns = {"ack-receipt": {"name": "ack-receipt", "gate": "auto",
                           "recipient_rule": {"type": "reply_to_thread"}}}
    problems = await validate_channel_refs(
        channel, workflow_store=wf,
        send_function_names=set(fns), send_functions=fns)
    assert problems == []


# ---------- repo seed files (loaded from the working tree) ----------


REPO_PLUGINS = dict(generators={"tailor-resume", "llm-brief"},
                    executors={"submit-application", "send-digest",
                               "channel-send"})


async def test_repo_seed_files_parse_and_cross_validate():
    storage = MemoryStorage()
    wf = WorkflowStore(storage, **REPO_PLUGINS)
    await wf.seed_dir("workflows")
    assert await wf.get("channel-email") is not None
    ch = ChannelStore(storage)
    assert await ch.seed_dir("channels") == 1
    channel = await ch.get("email")
    assert channel["status"] == "active"
    assert channel["transport"] == "console"
    assert channel["workflow"] == "channel-email"
    assert channel["poll_interval"] == 300.0
    assert channel["triage"]["tier"] == "bulk"
    assert set(channel["triage"]["routes"]) == {"file", "draft_reply"}
    assert "auto_ack" not in channel["triage"]["routes"]   # no default send fn
    assert await validate_channel_refs(channel, workflow_store=wf) == []


async def test_seeded_channel_email_workflow_shape():
    storage = MemoryStorage()
    wf_store = WorkflowStore(storage, **REPO_PLUGINS)
    await wf_store.seed_dir("workflows")
    wf = await wf_store.get("channel-email")
    assert wf["status"] == "active"
    items = wf["items"]
    assert items["collection"] == "wf-channel-email-items"
    assert items["title_field"] == "subject"
    assert set(items["fields"]) == {"subject", "sender", "to", "thread_id",
                                    "provider_id", "rfc_message_id", "body_text",
                                    "received_at", "triage_route", "triage_reason",
                                    "triage_status"}
    assert items["fields"]["body_text"]["type"] == "markdown"
    assert items["fields"]["received_at"]["type"] == "timestamp"
    assert items["fields"]["triage_status"]["type"] == "status"
    assert items["sort"] == ["-received_at"]
    assert wf["intake"] == {"skills": []}
    assert wf["actions"]["executor"] == "channel-send"   # Phase 2's send actions
    assert wf["actions"]["label"] == "send"
    assert wf["actions"]["approval_ttl"] == 3 * 86400
    assert wf["actions"]["draft_ttl"] == 14 * 86400
    assert wf["generate"] is None

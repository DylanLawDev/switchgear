import pytest

from switchgear.channels.sendfns import (
    BUILTIN_SLOTS,
    COLLECTION,
    SendFunctionError,
    SendFunctionStore,
)
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage


def make_store():
    storage = MemoryStorage()
    return SendFunctionStore(storage, Settings(_env_file=None)), storage


def fn_doc(**overrides):
    doc = {
        "name": "recruiter-followup",
        "description": "Follow up on a job application",
        "params": {
            "company": {"type": "enum", "values": ["stripe", "anthropic"]},
            "role": {"type": "string", "max_chars": 120},
        },
        "subject_template": "Following up on the {{role}} role",
        "body_template": "Hi,\n\nI applied for {{role}} at {{company}} on {{date}}.",
        "recipient_rule": {"type": "allowlist",
                           "addresses": ["Recruiting@Stripe.com"]},
        "gate": "approve",
        "rate_limit_per_day": 5,
        "enabled": True,
    }
    doc.update(overrides)
    return doc


# ---------- happy path + normalization ----------


async def test_save_roundtrip_normalizes_and_stamps():
    store, storage = make_store()
    doc = await store.save(fn_doc())
    assert doc["name"] == "recruiter-followup"
    assert doc["recipient_rule"]["addresses"] == ["recruiting@stripe.com"]
    assert doc["source"] == "user"
    assert doc["created_at"] == doc["updated_at"]
    stored = await storage.get(COLLECTION, "recruiter-followup")
    assert stored["subject_template"] == doc["subject_template"]


async def test_save_applies_safe_defaults():
    store, _ = make_store()
    minimal = fn_doc()
    for key in ("gate", "rate_limit_per_day", "enabled"):
        minimal.pop(key)
    doc = await store.save(minimal)
    assert doc["gate"] == "approve"          # default gate is the safe one
    assert doc["rate_limit_per_day"] == 5
    assert doc["enabled"] is True


async def test_update_preserves_created_at():
    store, _ = make_store()
    first = await store.save(fn_doc())
    second = await store.save(fn_doc(description="edited"))
    assert second["created_at"] == first["created_at"]
    assert second["description"] == "edited"


# ---------- name / description ----------


async def test_rejects_bad_names_and_missing_description():
    store, _ = make_store()
    for bad in ("", "UPPER", "x", "a" * 80, None):
        with pytest.raises(SendFunctionError):
            await store.save(fn_doc(name=bad))
    with pytest.raises(SendFunctionError):     # reserved for the reply counter
        await store.save(fn_doc(name="builtin-reply"))
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(description=""))
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(description=None))


# ---------- params schema ----------


async def test_param_type_matrix():
    store, _ = make_store()
    with pytest.raises(SendFunctionError):     # unknown type
        await store.save(fn_doc(params={"x": {"type": "blob"}}))
    with pytest.raises(SendFunctionError):     # string needs max_chars
        await store.save(fn_doc(params={"x": {"type": "string"}}))
    with pytest.raises(SendFunctionError):     # max_chars cap is 2000
        await store.save(fn_doc(
            params={"x": {"type": "string", "max_chars": 2001}}))
    with pytest.raises(SendFunctionError):     # max_chars must be >= 1
        await store.save(fn_doc(
            params={"x": {"type": "string", "max_chars": 0}}))
    with pytest.raises(SendFunctionError):     # max_chars must be >= 1
        await store.save(fn_doc(
            params={"x": {"type": "string", "max_chars": -5}}))
    with pytest.raises(SendFunctionError):     # enum needs non-empty values
        await store.save(fn_doc(params={"x": {"type": "enum", "values": []}}))
    with pytest.raises(SendFunctionError):     # not a mapping
        await store.save(fn_doc(params=["role"]))
    ok = await store.save(fn_doc(params={
        "x": {"type": "string", "max_chars": 2000},
        "n": {"type": "number"},
        "e": {"type": "enum", "values": ["a"]},
    }, subject_template="s {{x}}", body_template="b {{n}} {{e}}"))
    assert set(ok["params"]) == {"x", "n", "e"}


async def test_param_names_validated_and_reserved_names_blocked():
    store, _ = make_store()
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(params={"Bad Name": {"type": "number"}}))
    for reserved in ("to", "message_key", *BUILTIN_SLOTS):
        with pytest.raises(SendFunctionError):
            await store.save(fn_doc(params={reserved: {"type": "number"}}))


# ---------- templates ----------


async def test_template_slots_must_be_declared_or_builtin():
    store, _ = make_store()
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(subject_template="Hello {{whom}}"))
    doc = await store.save(fn_doc(
        body_template="From {{sender}} on {{date}} about {{role}}."))
    assert "{{sender}}" in doc["body_template"]


async def test_malformed_placeholders_rejected():
    store, _ = make_store()
    for bad in ("Hi {{role}", "Hi {{ role }}", "Hi {{"):
        with pytest.raises(SendFunctionError):
            await store.save(fn_doc(subject_template=bad))
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(subject_template=""))


async def test_nested_brace_placeholder_rejected():
    store, _ = make_store()
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(subject_template="{{role{{date}}}}"))
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(body_template="{{role{{date}}}}"))


async def test_undeclared_slot_in_body_template_only_rejected():
    store, _ = make_store()
    with pytest.raises(SendFunctionError):     # subject is clean; body is not
        await store.save(fn_doc(subject_template="Following up on the role",
                                body_template="Hi, about {{whom}}."))


# ---------- recipient rules ----------


async def test_recipient_rule_matrix():
    store, _ = make_store()
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(recipient_rule={"type": "broadcast"}))
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(recipient_rule={"type": "fixed"}))
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(
            recipient_rule={"type": "fixed", "address": "not-an-email"}))
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(recipient_rule={"type": "allowlist",
                                                "addresses": []}))
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(recipient_rule={"type": "allowlist",
                                                "addresses": ["ok@x.com", "junk"]}))
    fixed = await store.save(fn_doc(
        recipient_rule={"type": "fixed", "address": "VIP@Corp.com"}))
    assert fixed["recipient_rule"]["address"] == "vip@corp.com"
    for rule in ({"type": "owner"}, {"type": "reply_to_thread"}):
        assert (await store.save(fn_doc(recipient_rule=rule)))["recipient_rule"] == rule


# ---------- gate: the structural rule ----------


async def test_gate_auto_requires_warm_recipient_rule():
    store, _ = make_store()
    with pytest.raises(SendFunctionError):    # auto + fixed = cold auto: never
        await store.save(fn_doc(
            gate="auto", recipient_rule={"type": "fixed", "address": "a@b.com"}))
    with pytest.raises(SendFunctionError):    # auto + allowlist: never
        await store.save(fn_doc(gate="auto"))
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(gate="yolo"))
    for rule in ({"type": "owner"}, {"type": "reply_to_thread"}):
        doc = await store.save(fn_doc(gate="auto", recipient_rule=rule))
        assert doc["gate"] == "auto"


# ---------- rate limit / enabled ----------


async def test_rate_limit_validation():
    store, _ = make_store()
    for bad in (True, -1, "5", 2.5):
        with pytest.raises(SendFunctionError):
            await store.save(fn_doc(rate_limit_per_day=bad))
    assert (await store.save(fn_doc(rate_limit_per_day=0)))["rate_limit_per_day"] == 0


async def test_enabled_must_be_bool():
    store, _ = make_store()
    with pytest.raises(SendFunctionError):
        await store.save(fn_doc(enabled="yes"))


# ---------- reads / delete / audit ----------


async def test_get_list_names_delete():
    store, _ = make_store()
    await store.save(fn_doc())
    await store.save(fn_doc(name="ack", recipient_rule={"type": "reply_to_thread"},
                            gate="auto"))
    assert await store.get("nope") is None
    assert [d["name"] for d in await store.list()] == ["ack", "recruiter-followup"]
    assert all("_id" not in d for d in await store.list())
    assert await store.names() == {"ack", "recruiter-followup"}
    assert await store.delete("ack") is True
    assert await store.delete("ack") is False
    assert await store.names() == {"recruiter-followup"}


async def test_writes_are_audited():
    store, storage = make_store()
    await store.save(fn_doc())
    await store.delete("recruiter-followup")
    actions = [a["action"] for a in await storage.query("audit")]
    assert "sendfn_save" in actions
    assert "sendfn_delete" in actions

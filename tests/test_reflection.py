import json

import pytest

from switchgear.config import Settings
from switchgear.memory.embeddings import FakeEmbedder
from switchgear.memory.reflection import REFLECTION_PROMPT, ReflectionPass
from switchgear.memory.store import MemoryStore
from switchgear.storage.memory import MemoryStorage
from tests.fakes import FakeGateway

S = Settings(_env_file=None, owner_email="me@example.com")

MESSAGES = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "Actually, always write commits in imperative mood."},
    {"role": "assistant", "content": None,
     "tool_calls": [{"id": "c1", "type": "function",
                     "function": {"name": "storage", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "{}"},
    {"role": "assistant", "content": "Noted — imperative mood from now on."},
]

PROPOSALS = json.dumps({"memories": [
    {"text": "Write commits in imperative mood", "type": "core", "importance": 8},
    {"text": "Owner is preparing a talk for PyCon", "type": "episodic", "importance": 4},
]})


class Clock:
    def __init__(self, now=2000.0):
        self.now = now

    def __call__(self):
        return self.now


def make_pass(storage=None, completions=None, clock=None):
    storage = storage or MemoryStorage()
    gw = FakeGateway([], completions=completions)
    store = MemoryStore(storage, FakeEmbedder(), S)
    rp = ReflectionPass(gw, store, storage, S, clock=clock or Clock())
    return rp, gw, store, storage


async def seed_conversation(storage, conv_id="c1", messages=None, **extra):
    await storage.put("conversations", conv_id, {
        "messages": list(MESSAGES) if messages is None else messages,
        "title": "t", "updated_at": 1.0, **extra})


def test_reflection_interval_default():
    assert Settings(_env_file=None).memory_reflection_min_interval == 600


async def test_missing_conversation_does_not_run():
    rp, gw, _store, _db = make_pass()
    out = await rp.maybe_reflect("ghost")
    assert out == {"ran": False, "saved": 0, "reason": "no conversation"}
    assert gw.complete_calls == []


async def test_throttle_window_respected():
    clock = Clock(1000.0)
    rp, gw, _store, db = make_pass(clock=clock)
    await seed_conversation(db, last_reflection_at=900.0)
    out = await rp.maybe_reflect("c1")
    assert out == {"ran": False, "saved": 0, "reason": "throttled"}
    assert gw.complete_calls == []
    clock.now = 1500.0  # 900 + 600 <= now: window elapsed, pass runs
    assert (await rp.maybe_reflect("c1"))["ran"] is True


async def test_no_new_turns_does_not_run():
    rp, gw, _store, db = make_pass()
    await seed_conversation(db, reflection_cursor=len(MESSAGES))
    out = await rp.maybe_reflect("c1")
    assert out == {"ran": False, "saved": 0, "reason": "no new turns"}
    assert gw.complete_calls == []


async def test_tool_only_tail_counts_as_no_new_turns():
    tail = [{"role": "tool", "tool_call_id": "c9", "content": "{}"},
            {"role": "assistant", "content": None, "tool_calls": []}]
    rp, gw, _store, db = make_pass()
    await seed_conversation(db, messages=list(MESSAGES) + tail,
                            reflection_cursor=len(MESSAGES))
    assert (await rp.maybe_reflect("c1"))["reason"] == "no new turns"
    assert gw.complete_calls == []


async def test_happy_path_saves_proposals_and_advances_cursor():
    clock = Clock(2000.0)
    rp, gw, _store, db = make_pass(completions=[PROPOSALS], clock=clock)
    await seed_conversation(db)
    out = await rp.maybe_reflect("c1")
    assert out == {"ran": True, "saved": 2, "reason": None}
    call = gw.complete_calls[0]
    assert call["tier"] == "bulk" and call["tools"] is None
    assert call["messages"][0] == {"role": "system", "content": REFLECTION_PROMPT}
    assert "imperative mood" in call["messages"][1]["content"]  # transcript excerpt
    mems = await db.query("memories")
    assert {m["text"] for m in mems} == {
        "Write commits in imperative mood", "Owner is preparing a talk for PyCon"}
    assert all(m["source"] == "reflection" and m["conversation_id"] == "c1"
               for m in mems)
    doc = await db.get("conversations", "c1")
    assert doc["reflection_cursor"] == len(MESSAGES)
    assert doc["last_reflection_at"] == 2000.0
    assert doc["title"] == "t"  # unrelated fields preserved


async def test_existing_memories_are_shown_to_the_model():
    rp, gw, store, db = make_pass(completions=['{"memories": []}'])
    await store.save(text="Owner prefers dark mode", type="core", importance=6)
    await seed_conversation(db)
    await rp.maybe_reflect("c1")
    assert "Owner prefers dark mode" in gw.complete_calls[0]["messages"][1]["content"]


async def test_cursor_limits_transcript_to_new_turns():
    clock = Clock(2000.0)
    rp, gw, _store, db = make_pass(
        completions=['{"memories": []}', '{"memories": []}'], clock=clock)
    await seed_conversation(db)
    await rp.maybe_reflect("c1")
    doc = await db.get("conversations", "c1")
    doc["messages"] = doc["messages"] + [{"role": "user", "content": "brand new turn"}]
    await db.put("conversations", "c1", doc)
    clock.now += 601
    await rp.maybe_reflect("c1")
    second = gw.complete_calls[1]["messages"][1]["content"]
    assert "brand new turn" in second
    assert "imperative mood" not in second  # already-reflected turns excluded


async def test_empty_proposals_still_advance_cursor():
    rp, _gw, _store, db = make_pass(completions=['{"memories": []}'])
    await seed_conversation(db)
    out = await rp.maybe_reflect("c1")
    assert out == {"ran": True, "saved": 0, "reason": None}
    assert await db.query("memories") == []
    assert (await db.get("conversations", "c1"))["reflection_cursor"] == len(MESSAGES)


async def test_malformed_json_is_dropped_but_pass_completes():
    rp, _gw, _store, db = make_pass(completions=["sorry, no JSON today"])
    await seed_conversation(db)
    out = await rp.maybe_reflect("c1")
    assert out == {"ran": True, "saved": 0, "reason": "unparseable"}
    assert await db.query("memories") == []
    assert (await db.get("conversations", "c1"))["reflection_cursor"] == len(MESSAGES)


async def test_fenced_json_is_accepted():
    fenced = "```json\n" + PROPOSALS + "\n```"
    rp, _gw, _store, db = make_pass(completions=[fenced])
    await seed_conversation(db)
    assert (await rp.maybe_reflect("c1"))["saved"] == 2


async def test_invalid_type_and_oversized_text_are_skipped():
    bad = json.dumps({"memories": [
        {"text": "fine", "type": "core", "importance": 5},
        {"text": "nope", "type": "banana", "importance": 5},
        {"text": "x" * 2000, "type": "episodic", "importance": 5},  # > memory_max_chars
    ]})
    rp, _gw, _store, db = make_pass(completions=[bad])
    await seed_conversation(db)
    out = await rp.maybe_reflect("c1")
    assert out["ran"] is True and out["saved"] == 1
    assert [m["text"] for m in await db.query("memories")] == ["fine"]


async def test_proposals_capped_at_five():
    many = json.dumps({"memories": [
        {"text": f"memory number {i}", "type": "episodic", "importance": 3}
        for i in range(7)]})
    rp, _gw, _store, db = make_pass(completions=[many])
    await seed_conversation(db)
    assert (await rp.maybe_reflect("c1"))["saved"] == 5
    assert len(await db.query("memories")) == 5


async def test_gateway_failure_engages_throttle_but_cursor_untouched():
    clock = Clock(2000.0)
    rp, _gw, _store, db = make_pass(
        completions=[RuntimeError("bulk model down")], clock=clock)
    await seed_conversation(db)
    with pytest.raises(RuntimeError):
        await rp.maybe_reflect("c1")
    doc = await db.get("conversations", "c1")
    assert "reflection_cursor" not in doc  # turns will be retried once gateway recovers
    assert doc["last_reflection_at"] == 2000.0  # throttle engaged despite the failure
    assert doc["title"] == "t"  # unrelated fields preserved


async def test_throttled_retry_after_gateway_failure_skips_second_gateway_call():
    clock = Clock(2000.0)
    rp, gw, _store, db = make_pass(
        completions=[RuntimeError("bulk model down")], clock=clock)
    await seed_conversation(db)
    with pytest.raises(RuntimeError):
        await rp.maybe_reflect("c1")
    assert len(gw.complete_calls) == 1
    clock.now = 2100.0  # inside the 600s window
    out = await rp.maybe_reflect("c1")
    assert out == {"ran": False, "saved": 0, "reason": "throttled"}
    assert len(gw.complete_calls) == 1  # gateway not hammered while throttled


async def test_turn_appended_during_llm_call_survives_the_trailing_write():
    """A chat turn persisted while gateway.complete() is in flight must not be
    clobbered by reflection's trailing write, and must stay past the cursor so
    the NEXT pass processes it."""
    storage = MemoryStorage()

    class RacingGateway(FakeGateway):
        async def complete(self, tier, messages, tools=None):
            doc = await storage.get("conversations", "c1")
            doc["messages"] = doc["messages"] + [
                {"role": "user", "content": "sent while reflecting"}]
            await storage.put("conversations", "c1", doc)
            return await super().complete(tier, messages, tools)

    gw = RacingGateway([], completions=['{"memories": []}'])
    store = MemoryStore(storage, FakeEmbedder(), S)
    rp = ReflectionPass(gw, store, storage, S, clock=Clock())
    await seed_conversation(storage)
    out = await rp.maybe_reflect("c1")
    assert out["ran"] is True
    doc = await storage.get("conversations", "c1")
    contents = [m.get("content") for m in doc["messages"]]
    assert "sent while reflecting" in contents  # turn survives the write
    assert doc["reflection_cursor"] == len(MESSAGES)  # pre-append length
    assert doc["title"] == "t"


async def test_conversation_deleted_mid_flight_skips_the_write():
    storage = MemoryStorage()

    class DeletingGateway(FakeGateway):
        async def complete(self, tier, messages, tools=None):
            await storage.delete("conversations", "c1")
            return await super().complete(tier, messages, tools)

    gw = DeletingGateway([], completions=[PROPOSALS])
    store = MemoryStore(storage, FakeEmbedder(), S)
    rp = ReflectionPass(gw, store, storage, S, clock=Clock())
    await seed_conversation(storage)
    out = await rp.maybe_reflect("c1")
    assert out == {"ran": True, "saved": 2, "reason": None}
    assert await storage.get("conversations", "c1") is None  # not resurrected


async def test_successful_pass_starts_a_new_throttle_window():
    clock = Clock(2000.0)
    rp, gw, _store, db = make_pass(completions=['{"memories": []}'], clock=clock)
    await seed_conversation(db)
    assert (await rp.maybe_reflect("c1"))["ran"] is True
    clock.now = 2100.0  # inside the 600 s window
    assert (await rp.maybe_reflect("c1"))["reason"] == "throttled"
    assert len(gw.complete_calls) == 1

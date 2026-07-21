import json

import pytest

from switchgear.conversations import ConversationStore, ui_history
from switchgear.storage.memory import MemoryStorage


def test_ui_history_keeps_messages_and_pairs_tool_results():
    stored = [
        {"role": "system", "content": "hidden"},
        {"role": "user", "content": "update it"},
        {"role": "assistant", "content": "I'll inspect it", "tool_calls": [{
            "id": "call-1", "type": "function",
            "function": {"name": "resources", "arguments": json.dumps({
                "op": "update", "name": "career-bank", "content": "new"})},
        }]},
        {"role": "tool", "tool_call_id": "call-1", "content": json.dumps({
            "queued": True, "id": "pending-1", "name": "career-bank"})},
        {"role": "assistant", "content": "Queued for approval."},
    ]

    assert ui_history(stored) == [
        {"kind": "message", "role": "user", "content": "update it"},
        {"kind": "message", "role": "assistant", "content": "I'll inspect it"},
        {"kind": "tool", "call_id": "call-1", "name": "resources",
         "args": {"op": "update", "name": "career-bank", "content": "new"},
         "result": {"queued": True, "id": "pending-1", "name": "career-bank"}},
        {"kind": "message", "role": "assistant", "content": "Queued for approval."},
    ]


def test_ui_history_preserves_non_json_tool_output():
    stored = [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "c", "function": {"name": "read", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c", "content": "plain text"},
    ]
    assert ui_history(stored)[0]["result"] == "plain text"


@pytest.mark.asyncio
async def test_load_ui_includes_persisted_partial_run_and_status():
    store = ConversationStore(MemoryStorage())
    await store.save("c1", [{"role": "user", "content": "hello"}])
    await store.save_live("c1", [
        {"kind": "message", "role": "assistant", "content": "working"},
        {"kind": "tool", "call_id": "", "name": "resources", "args": {"op": "list"}},
    ])

    assert await store.load_ui("c1") == [
        {"kind": "message", "role": "user", "content": "hello"},
        {"kind": "message", "role": "assistant", "content": "working"},
        {"kind": "tool", "call_id": "", "name": "resources", "args": {"op": "list"}},
        {"kind": "status", "status": "running"},
    ]

"""channel_send + channel_messages (spec §5.3).

channel_send is the agent's ONLY route to non-owner recipients, and it can
only invoke owner-authored send functions — the service enforces recipients,
templates, suppression, rate limits, and gating; the tool result never
reveals a bypass (sent vs pending_approval is all the agent learns).
channel_messages reads stored, sanitized messages; reading taints nothing by
itself — the constrained action surface is what makes that safe."""

import json
import logging

from switchgear.channels.send import ChannelSendError
from switchgear.tools.base import Tool

logger = logging.getLogger(__name__)

CHANNEL_WORKFLOW = "channel-email"
MESSAGE_KEY_PREFIX = "msg-"  # ingest keys; synthetic out-* items are filtered
LIST_CAP = 50

SEND_DESCRIPTION = (
    "Send email through a named, owner-authored send function. Each function "
    "fixes its own recipients, templates, and approval gate — you supply only "
    "the declared params. To reply to a stored message, pass its key as the "
    "'message_key' param (required by reply_to_thread functions); allowlist "
    "functions take the recipient as a 'to' param. Returns status 'sent', or "
    "'pending_approval' with the draft key when the owner must approve first — "
    "that key names a draft the owner reviews and approves in the UI; it is "
    "not a message you can read back via channel_messages."
)

MESSAGES_DESCRIPTION = (
    "Read the agent inbox (sanitized stored messages). op='list' returns the "
    "newest messages (key, subject, sender, received_at, triage_status); "
    "op='read' with a key returns one message including its body_text."
)


def make_channel_send_tool(service) -> Tool:
    async def channel_send(function: str, params: dict | None = None) -> str:
        try:
            result = await service.send(function, dict(params or {}),
                                        actor="agent")
        except ChannelSendError as e:
            return json.dumps({"error": str(e)})
        except Exception:
            # The registry's fallback wrapper would stringify raw exception
            # detail back to the model; degrade to an opaque error instead.
            logger.exception("channel_send %s failed internally", function)
            return json.dumps({"error": "internal send failure"})
        return json.dumps(result)

    return Tool(
        name="channel_send",
        description=SEND_DESCRIPTION,
        parameters={"type": "object", "properties": {
            "function": {"type": "string",
                         "description": "send function name"},
            "params": {"type": "object",
                       "description": "the function's declared params "
                                      "(plus message_key/to where required)"},
        }, "required": ["function"]},
        handler=channel_send,
    )


def make_channel_messages_tool(workflow_store, storage) -> Tool:
    async def channel_messages(op: str, key: str | None = None) -> str:
        wf = await workflow_store.get(CHANNEL_WORKFLOW)
        if wf is None:
            return json.dumps({"error": "channel workflow not found"})
        collection = wf["items"]["collection"]
        if op == "list":
            docs = await storage.query(collection)
            docs = [d for d in docs
                    if str(d.get("key") or "").startswith(MESSAGE_KEY_PREFIX)]
            docs.sort(key=lambda d: d.get("received_at") or 0, reverse=True)
            return json.dumps([{
                "key": d.get("key"), "subject": d.get("subject"),
                "sender": d.get("sender"),
                "received_at": d.get("received_at"),
                "triage_status": d.get("triage_status"),
            } for d in docs[:LIST_CAP]])
        if op == "read":
            if not key:
                return json.dumps({"error": "read requires a key"})
            if not key.startswith(MESSAGE_KEY_PREFIX):
                # Same shape as a missing doc: synthetic out-* items (whose
                # keys the agent learns from pending_approval responses) and
                # any other non-message document stay unreadable, with no
                # existence oracle.
                return json.dumps({"error": "message not found"})
            doc = await storage.get(collection, key)
            if doc is None:
                return json.dumps({"error": "message not found"})
            allowed = ("key", *wf["items"]["fields"].keys())
            return json.dumps({k: doc.get(k) for k in allowed})
        return json.dumps({"error": "op must be 'list' or 'read'"})

    return Tool(
        name="channel_messages",
        description=MESSAGES_DESCRIPTION,
        parameters={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["list", "read"]},
            "key": {"type": "string", "description": "message key for read"},
        }, "required": ["op"]},
        handler=channel_messages,
    )

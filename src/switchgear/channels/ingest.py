"""Ingest pipeline (spec §4): poll → sanitize → dedupe → store (→ triage).

Sanitization runs BEFORE storage and before any model ever sees a body; the
stored body_text is the only body kept — raw MIME stays with the provider
(provider_id links back). No image fetching anywhere, ever. Items are written
through save_item — the SAME validated intake path the workflow_items tool
uses — with a deterministic msg-<hash> key, so re-polls and cursor resyncs
dedupe by construction. Phase 1 always constructs with triage=None; Phase 3
supplies the quarantined classifier via the triage seam.
"""

import hashlib
import html as html_mod
import logging
import re
import time
from uuid import uuid4

from switchgear.config import Settings
from switchgear.storage.base import Storage
from switchgear.tools.workflow_items import save_item

logger = logging.getLogger(__name__)

STATE_COLLECTION = "channel-state"

_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b.*?</\1\s*>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
# ZWSP, ZWNJ, ZWJ, BOM, soft hyphen — the hidden-text carriers (spec §4.2)
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍﻿­"))


def sanitize_body(body: str | None, is_html: bool, max_chars: int) -> str:
    text = str(body or "")
    if is_html:
        text = _SCRIPT_STYLE_RE.sub(" ", text)
        text = _TAG_RE.sub(" ", text)
        text = html_mod.unescape(text)
    text = text.translate(_INVISIBLE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[truncated]"
    return text


def message_key(provider_id: str) -> str:
    return f"msg-{hashlib.sha256(str(provider_id).encode()).hexdigest()[:16]}"


class ChannelIngest:
    def __init__(self, channel: dict, transport, workflow_store,
                 storage: Storage, settings: Settings, triage=None):
        self._channel = channel
        self._transport = transport
        self._workflows = workflow_store
        self._db = storage
        self._s = settings
        self._triage = triage

    async def poll(self) -> dict:
        name = self._channel["name"]
        wf = await self._workflows.get(self._channel["workflow"])
        if wf is None or wf.get("status") != "active":
            logger.warning("channel %s: workflow %r missing/inactive — poll skipped",
                           name, self._channel["workflow"])
            return {"fetched": 0, "stored": 0, "duplicates": 0, "failed": 0}
        state = await self._db.get(STATE_COLLECTION, name) or {}
        messages, new_cursor = await self._transport.fetch_new(state.get("cursor"))
        collection = wf["items"]["collection"]
        stored = duplicates = failed = 0
        for m in messages:
            key = message_key(m["provider_id"])
            if await self._db.get(collection, key) is not None:
                duplicates += 1
                continue
            item = {
                "subject": str(m.get("subject") or ""),
                "sender": str(m.get("sender") or ""),
                "to": str(m.get("to") or ""),
                "thread_id": str(m.get("thread_id") or ""),
                "provider_id": str(m["provider_id"]),
                "rfc_message_id": m.get("rfc_message_id"),
                "body_text": sanitize_body(m.get("body"),
                                           bool(m.get("body_is_html")),
                                           self._s.channel_body_max_chars),
                "received_at": m.get("received_at"),
                "triage_status": "pending",
                "triage_route": None,
                "triage_reason": None,
            }
            result = await save_item(self._workflows, self._db,
                                     self._channel["workflow"], item, key=key)
            if result.get("status") != "new":
                # Deliberate policy: failed messages are intentionally not
                # retried under normal cursor flow. Validation failures are
                # deterministic (schema mismatch / inactive workflow), so
                # retrying would fail identically every poll, and the
                # message remains recoverable at the provider via
                # provider_id; the failed count in the poll audit is the
                # owner's signal.
                logger.warning("channel %s: message %s not stored: %s",
                               name, key, result)
                failed += 1
                continue
            stored += 1
            if self._triage is not None:
                try:
                    doc = await self._db.get(collection, key)
                    await self._triage.triage_message(doc)
                except Exception:
                    logger.exception("channel %s: triage failed for %s", name, key)
        await self._db.put(STATE_COLLECTION, name,
                           {"cursor": new_cursor, "last_poll": time.time()})
        await self._db.put("audit", f"channel-{uuid4().hex}", {
            "action": "channel_poll", "name": name, "fetched": len(messages),
            "stored": stored, "failed": failed, "at": time.time()})
        return {"fetched": len(messages), "stored": stored,
                "duplicates": duplicates, "failed": failed}

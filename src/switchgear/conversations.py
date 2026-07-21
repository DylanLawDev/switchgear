import json
import time

from switchgear.storage.base import Storage


class ConversationStore:
    def __init__(self, storage: Storage):
        self._db = storage

    async def load(self, conversation_id: str) -> list[dict]:
        doc = await self._db.get("conversations", conversation_id)
        return doc["messages"] if doc else []

    async def load_ui(self, conversation_id: str) -> list[dict]:
        doc = await self._db.get("conversations", conversation_id)
        if not doc:
            return []
        out = ui_history(doc.get("messages", []))
        out.extend(doc.get("live_items", []))
        if doc.get("live_status") == "running":
            out.append({"kind": "status", "status": "running"})
        return out

    async def save(self, conversation_id: str, messages: list[dict],
                   title: str | None = None, clear_live: bool = False) -> None:
        # Merge into the existing doc rather than overwrite it: reflection
        # (storage layer phase 3) persists reflection_cursor/last_reflection_at
        # into this same document, and a blind overwrite here would silently
        # reset its throttle state on every following chat turn.
        existing = await self._db.get("conversations", conversation_id) or {}
        existing.update({
            "messages": messages,
            "title": title or existing.get("title") or "untitled",
            "updated_at": time.time()})
        if clear_live:
            existing.pop("live_items", None)
            existing.pop("live_status", None)
        await self._db.put("conversations", conversation_id, existing)

    async def save_live(self, conversation_id: str, items: list[dict],
                        status: str = "running") -> None:
        existing = await self._db.get("conversations", conversation_id) or {}
        existing.update({
            "live_items": items,
            "live_status": status,
            "updated_at": time.time(),
        })
        await self._db.put("conversations", conversation_id, existing)

    async def list(self) -> list[dict]:
        docs = await self._db.query("conversations")
        docs.sort(key=lambda d: d.get("updated_at", 0), reverse=True)
        return [{"_id": d["_id"], "title": d.get("title"),
                 "updated_at": d.get("updated_at")} for d in docs]


def _decode_json(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def ui_history(messages: list[dict]) -> list[dict]:
    """Convert the stored LLM transcript into stable, renderable chat events."""
    out: list[dict] = []
    calls: dict[str, dict] = {}
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content:
            out.append({"kind": "message", "role": role, "content": content})
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                fn = call.get("function") or {}
                item = {
                    "kind": "tool",
                    "call_id": call.get("id") or "",
                    "name": fn.get("name") or "unknown",
                    "args": _decode_json(fn.get("arguments") or "{}"),
                }
                out.append(item)
                if item["call_id"]:
                    calls[item["call_id"]] = item
        elif role == "tool":
            item = calls.get(message.get("tool_call_id"))
            if item is not None:
                item["result"] = _decode_json(content)
    return out

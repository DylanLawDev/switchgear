"""Agent-initiated resource writes, gated by an owner-controlled mode.

Modes (stored in the `resource-settings` collection, key `resources`):
- read-only : agent writes are refused.
- prompt    : (default) writes queue as pending edits; the owner approves or
              rejects each one in the UI (spec §3.5 / contract §6.3).
- full      : writes apply immediately, stamped source="agent".

This service is the ONLY relaxation of the resources-are-agent-read-only
invariant; every path is audited, including refused attempts
("resource_agent_refused") from propose() and approve(). Pending-edit
`created_at` is iso8601 (frozen API contract) unlike the epoch floats used
elsewhere.

The `resource-settings` (write mode) and `resource-pending` (approval queue)
collections are listed in the storage tool's PROTECTED_COLLECTIONS so the
agent cannot self-escalate its own write mode or forge pending edits by
writing them directly with the raw storage tool — this service is the only
writer.
"""

import time
from datetime import datetime, timezone
from uuid import uuid4

from switchgear.resources.store import ResourceError, ResourceStore
from switchgear.storage.base import Storage
from switchgear.tools.base import current_origin

MODES = ("read-only", "prompt", "full")
DEFAULT_MODE = "prompt"
OPS = ("create", "update", "delete")
SETTINGS_COLLECTION = "resource-settings"
SETTINGS_KEY = "resources"
PENDING_COLLECTION = "resource-pending"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentWriteService:
    def __init__(self, store: ResourceStore, storage: Storage):
        self._store = store
        self._db = storage

    async def _audit(self, action: str, name: str, detail: str = "") -> None:
        await self._db.put("audit", f"resource-agent-{uuid4().hex}", {
            "action": action, "name": name, "detail": detail, "at": time.time()})

    async def get_mode(self) -> str:
        doc = await self._db.get(SETTINGS_COLLECTION, SETTINGS_KEY)
        mode = (doc or {}).get("write_mode", DEFAULT_MODE)
        return mode if mode in MODES else DEFAULT_MODE

    async def set_mode(self, mode: str) -> str:
        if mode not in MODES:
            raise ResourceError(
                f"unknown write_mode {mode!r} (use {', '.join(MODES)})")
        await self._db.put(SETTINGS_COLLECTION, SETTINGS_KEY, {"write_mode": mode})
        await self._audit("resource_write_mode", SETTINGS_KEY, mode)
        return mode

    async def propose(self, op: str, name: str, kind: str = "",
                      description: str = "", content: str = "") -> dict:
        mode = await self.get_mode()
        try:
            if mode == "read-only":
                raise ResourceError(
                    "resource writes are disabled (write_mode=read-only)")
            if op not in OPS:
                raise ResourceError(f"unknown op {op!r} (use {', '.join(OPS)})")
            existing = await self._store.get(name)
            if op == "create" and existing is not None:
                raise ResourceError(f"{name}: already exists (use update)")
            if op in ("update", "delete") and existing is None:
                raise ResourceError(f"{name}: not found")
            if op == "update":
                kind = kind or existing["kind"]
                description = description or existing.get("description", "")
            if op != "delete":
                await self._store.validate(name, kind, content)
            if mode == "full":
                await self._apply(op, name, kind, description, content)
        except ResourceError as e:
            await self._audit("resource_agent_refused", name, str(e))
            raise
        if mode == "full":
            await self._audit("resource_agent_write", name, op)
            return {"applied": True, "op": op, "name": name}
        pending_id = uuid4().hex
        await self._db.put(PENDING_COLLECTION, pending_id, {
            "id": pending_id, "resource_name": name, "op": op,
            "kind": kind or None, "description": description,
            "old_content": existing["content"] if existing else None,
            "new_content": None if op == "delete" else content,
            "created_at": _now_iso(), "status": "pending",
            "origin": current_origin.get()})
        await self._audit("resource_agent_pending", name, op)
        return {"applied": False, "queued": True, "id": pending_id, "op": op,
                "name": name,
                "approval": {"kind": "resource_write", "id": pending_id},
                "note": "queued for owner approval"}

    async def _apply(self, op: str, name: str, kind: str, description: str,
                     content: str) -> None:
        if op == "delete":
            await self._store.delete(name)
        else:
            if op == "create" and await self._store.get(name) is not None:
                # Re-check: the resource may have been created between
                # propose()'s initial existence check and this apply (full
                # mode has no staleness guard like approve() does).
                raise ResourceError(f"{name}: already exists (use update)")
            await self._store.save(name, kind, description, content,
                                   source="agent")

    async def list_pending(self) -> list[dict]:
        docs = [d for d in await self._db.query(PENDING_COLLECTION)
                if d.get("status") == "pending"]
        docs.sort(key=lambda d: d.get("created_at", ""))
        return [{k: d.get(k) for k in
                 ("id", "resource_name", "op", "old_content", "new_content",
                  "created_at", "status", "origin")} for d in docs]

    async def get_proposal(self, pending_id: str) -> dict | None:
        return await self._db.get(PENDING_COLLECTION, pending_id)

    async def _resolve(self, pending_id: str, status: str) -> dict | None:
        doc = await self._db.get(PENDING_COLLECTION, pending_id)
        if doc is None or doc.get("status") != "pending":
            return None
        doc["status"] = status
        doc["resolved_at"] = _now_iso()
        await self._db.put(PENDING_COLLECTION, pending_id, doc)
        return doc

    async def approve(self, pending_id: str) -> bool:
        doc = await self._db.get(PENDING_COLLECTION, pending_id)
        if doc is None or doc.get("status") != "pending":
            return False
        current = await self._store.get(doc["resource_name"])
        current_content = current["content"] if current else None
        if current_content != doc.get("old_content"):
            msg = (f"{doc['resource_name']}: resource changed since this edit was "
                   "proposed — reject it and ask the agent to re-propose")
            await self._audit("resource_agent_refused", doc["resource_name"], msg)
            raise ResourceError(msg)
        await self._apply(doc["op"], doc["resource_name"], doc.get("kind") or "",
                          doc.get("description") or "",
                          doc.get("new_content") or "")
        await self._resolve(pending_id, "approved")
        await self._audit("resource_agent_approved", doc["resource_name"], doc["op"])
        return True

    async def reject(self, pending_id: str) -> bool:
        doc = await self._resolve(pending_id, "rejected")
        if doc is None:
            return False
        await self._audit("resource_agent_rejected", doc["resource_name"], doc["op"])
        return True

    async def reject_for_resource(self, name: str) -> int:
        count = 0
        for d in await self._db.query(PENDING_COLLECTION):
            if d.get("status") == "pending" and d.get("resource_name") == name:
                if await self.reject(d["id"]):
                    count += 1
        return count

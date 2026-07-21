import time
from datetime import datetime, timezone
from uuid import uuid4

from switchgear.tools.base import current_origin

COLLECTION = "definition-pending"


class DefinitionWriteError(Exception):
    pass


class DefinitionWriteService:
    def __init__(self, storage, stores: dict[str, object]):
        self._db = storage
        self._stores = stores

    async def propose(self, kind: str, text: str, origin: str | None = None) -> dict:
        store = self._stores.get(kind)
        if store is None:
            raise DefinitionWriteError(f"unsupported definition kind: {kind}")
        parsed = store.validate(text)
        name = parsed["name"]
        existing = await store.get(name)
        request_id = uuid4().hex
        doc = {"id": request_id, "kind": kind, "name": name,
               "op": "update" if existing else "create", "text": text,
               "old_text": (existing or {}).get("text"),
               "base_updated_at": (existing or {}).get("updated_at"),
               "status": "pending", "origin": origin or current_origin.get(),
               "created_at": datetime.now(timezone.utc).isoformat()}
        await self._db.put(COLLECTION, request_id, doc)
        await self._audit("pending", doc)
        return {"queued": True, "id": request_id, "kind": kind, "name": name,
                "approval": {"kind": "definition_write", "id": request_id}}

    async def get(self, request_id: str) -> dict | None:
        return await self._db.get(COLLECTION, request_id)

    async def list_pending(self) -> list[dict]:
        rows = await self._db.query(COLLECTION, where={"status": "pending"})
        rows.sort(key=lambda row: row.get("created_at", ""))
        return rows

    async def resolve(self, request_id: str, approved: bool) -> bool:
        doc = await self.get(request_id)
        if doc is None or doc.get("status") != "pending":
            return False
        store = self._stores[doc["kind"]]
        current = await store.get(doc["name"])
        if (current or {}).get("updated_at") != doc.get("base_updated_at"):
            raise DefinitionWriteError(
                f"{doc['kind']} {doc['name']} changed since this proposal")
        if approved:
            await store.save(doc["text"], source="agent", status="active")
        doc["status"] = "approved" if approved else "rejected"
        doc["resolved_at"] = datetime.now(timezone.utc).isoformat()
        await self._db.put(COLLECTION, request_id, doc)
        await self._audit(doc["status"], doc)
        return True

    async def _audit(self, action: str, doc: dict) -> None:
        await self._db.put("audit", f"definition-{uuid4().hex}", {
            "action": f"definition_{action}", "kind": doc["kind"],
            "name": doc["name"], "request_id": doc["id"], "at": time.time()})

import time
from datetime import datetime, timezone
from uuid import uuid4

from switchgear.skills.model import SkillParseError, parse_skill
from switchgear.tools.base import current_origin

PENDING_COLLECTION = "skill-pending"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillWriteError(Exception):
    pass


class SkillWriteService:
    def __init__(self, store, storage):
        self._store = store
        self._db = storage

    async def _audit(self, action: str, name: str, detail: str = "") -> None:
        await self._db.put("audit", f"skill-agent-{uuid4().hex}", {
            "action": action, "name": name, "detail": detail, "at": time.time()})

    async def propose(self, text: str) -> dict:
        try:
            parsed = parse_skill(text)
        except SkillParseError:
            raise
        name = parsed["name"]
        existing = await self._store.get(name)
        pending_id = uuid4().hex
        await self._db.put(PENDING_COLLECTION, pending_id, {
            "id": pending_id, "skill_name": name,
            "op": "update" if existing else "create", "text": text,
            "old_text": (existing or {}).get("text"),
            "base_updated_at": (existing or {}).get("updated_at"),
            "created_at": _now_iso(), "status": "pending",
            "origin": current_origin.get(),
        })
        await self._audit("skill_agent_pending", name)
        return {
            "applied": False, "queued": True, "id": pending_id,
            "name": name, "op": "update" if existing else "create",
            "approval": {"kind": "skill_write", "id": pending_id},
            "note": "queued for owner approval",
        }

    async def get_proposal(self, pending_id: str) -> dict | None:
        return await self._db.get(PENDING_COLLECTION, pending_id)

    async def list_pending(self) -> list[dict]:
        rows = await self._db.query(PENDING_COLLECTION, where={"status": "pending"})
        rows.sort(key=lambda row: row.get("created_at", ""))
        return rows

    async def approve(self, pending_id: str) -> bool:
        proposal = await self.get_proposal(pending_id)
        if proposal is None or proposal.get("status") != "pending":
            return False
        current = await self._store.get(proposal["skill_name"])
        if (current or {}).get("updated_at") != proposal.get("base_updated_at"):
            raise SkillWriteError(
                f"{proposal['skill_name']}: skill changed since this write was proposed")
        await self._store.save(proposal["text"], source="agent", status="active")
        await self._resolve(proposal, "approved")
        await self._audit("skill_agent_approved", proposal["skill_name"])
        return True

    async def reject(self, pending_id: str) -> bool:
        proposal = await self.get_proposal(pending_id)
        if proposal is None or proposal.get("status") != "pending":
            return False
        await self._resolve(proposal, "rejected")
        await self._audit("skill_agent_rejected", proposal["skill_name"])
        return True

    async def _resolve(self, proposal: dict, status: str) -> None:
        proposal["status"] = status
        proposal["resolved_at"] = _now_iso()
        await self._db.put(PENDING_COLLECTION, proposal["id"], proposal)

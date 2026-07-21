"""GatedActionService: the human-approval status machine for external actions.

Every security invariant from the old apply/service.py carries over verbatim:
the service is the SOLE writer of action records; "status" is never taken
from plugin or agent output; draft payloads are sanitized in code; approval
is enforced here, never in a prompt. Executors implement only domain behavior
(draft/precondition/execute) with dependencies injected at construction.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from uuid import uuid4

EDITABLE = {"draft", "failed"}
SUPERSEDABLE = {"draft", "approved", "failed"}


class ExecutionFailed(Exception):
    """Raised by an executor BEFORE any side effect: safe to re-approve."""


class ExecutionAmbiguous(Exception):
    """Raised by an executor when the side effect MAY have landed."""


@dataclass
class DraftResult:
    fields: list
    notes: str = ""
    extra: dict = field(default_factory=dict)
    error: str | None = None


def payload_hash(fields: list[dict]) -> str:
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def sanitize_field(raw: object) -> dict | None:
    if not isinstance(raw, dict) or raw.get("selector") is None:
        return None
    return {
        "selector": str(raw.get("selector")),
        "label": str(raw.get("label") or ""),
        "value": str(raw.get("value") or ""),
        "source": str(raw.get("source") or "agent"),
        "needs_you": bool(raw.get("needs_you", False)),
        "kind": str(raw.get("kind") or "text"),
    }


class GatedActionService:
    def __init__(self, storage, plugins, settings, clock=time.time):
        self._db = storage
        self._plugins = plugins
        self._s = settings
        self._now = clock
        self._exec_lock = asyncio.Lock()

    # ---------- helpers ----------

    @staticmethod
    def _coll(wf: dict) -> str:
        return wf["actions"]["collection"]

    @staticmethod
    def _kf(wf: dict) -> str:
        return wf["actions"]["key_field"]

    @staticmethod
    def _irf(wf: dict) -> str:
        return wf["actions"]["item_ref_field"]

    async def _audit(self, wf: dict, op: str, key: str, actor: str = "owner",
                     **extra) -> None:
        await self._db.put("audit", f"wfa-{uuid4().hex}", {
            "tool": "workflow-action", "workflow": wf["name"], "op": op,
            "key": key, "actor": actor, "at": self._now(), **extra})

    def _append_note(self, record: dict, note: str) -> None:
        existing = record.get("notes") or ""
        record["notes"] = f"{existing}\n{note}".strip() if existing else note

    async def _normalize(self, wf: dict, record: dict) -> dict:
        """Read-boundary normalization + lazy TTLs. Legacy 'submitted' is
        presented as 'executed' without rewriting the stored record; TTL
        transitions ARE persisted (and audited as system actor)."""
        record = dict(record)
        if record.get("status") == "submitted":
            record["status"] = "executed"
            return record
        now = self._now()
        key = record.get(self._kf(wf))
        if record.get("status") == "approved":
            approved_at = (record.get("approval") or {}).get("approved_at") or 0
            if now > approved_at + wf["actions"]["approval_ttl"]:
                record["status"] = "draft"
                record.pop("approval", None)
                record.pop("_id", None)  # storage.query() may have injected this
                await self._db.put(self._coll(wf), key, record)
                await self._audit(wf, "approval-expired", key, actor="system")
        elif record.get("status") == "draft":
            since = record.get("updated_at") or record.get("created_at") or now
            if now > since + wf["actions"]["draft_ttl"]:
                record["status"] = "expired"
                record.pop("_id", None)  # storage.query() may have injected this
                await self._db.put(self._coll(wf), key, record)
                await self._audit(wf, "draft-expired", key, actor="system")
        return record

    # ---------- reads ----------

    async def get(self, wf: dict, key: str) -> dict | None:
        record = await self._db.get(self._coll(wf), key)
        if record is None:
            return None
        return await self._normalize(wf, record)

    async def list(self, wf: dict) -> list[dict]:
        records = await self._db.query(self._coll(wf))
        out = [await self._normalize(wf, r) for r in records]
        out.sort(key=lambda r: r.get("created_at") or 0, reverse=True)
        return out

    # ---------- draft lifecycle ----------

    async def start_draft(self, wf: dict, item_key: str) -> dict:
        item = await self._db.get(wf["items"]["collection"], item_key)
        if item is None:
            return {"error": f"{wf['items']['label']} not found"}

        key = f"act-{uuid4().hex[:12]}"
        kf, irf = self._kf(wf), self._irf(wf)
        created_at = self._now()
        updated_at = self._now()
        record = {kf: key, irf: item_key, "status": "draft", "fields": [],
                  "notes": "", "created_at": created_at, "updated_at": updated_at,
                  "executed_at": None}
        # Pre-create before invoking the executor: even if it dies, the
        # draft (empty, unmapped) still exists for review.
        await self._db.put(self._coll(wf), key, record)

        executor = self._plugins.executor(wf["actions"]["executor"])
        try:
            result = await executor.draft(item)
        except Exception as e:
            result = DraftResult(fields=[], notes=f"draft failed: {type(e).__name__}: {e}",
                                 error=f"{type(e).__name__}: {e}")

        record.update(result.extra or {})
        # Plugin output can never set identity, lineage, status, approval, or
        # timestamps.
        record[kf], record[irf] = key, item_key
        record["status"] = "draft"
        record["created_at"] = created_at
        record["updated_at"] = updated_at
        record.pop("approval", None)
        record["executed_at"] = None
        record["fields"] = [f for f in map(sanitize_field, result.fields or [])
                            if f]
        record["notes"] = str(result.notes or "")
        await self._db.put(self._coll(wf), key, record)
        await self._audit(wf, "draft", key, item_key=item_key)
        if result.error:
            return {**record, "error": result.error}
        return record

    async def update_fields(self, wf: dict, key: str, fields: list[dict]) -> dict | None:
        record = await self.get(wf, key)
        if record is None:
            return None
        if record.get("status") not in EDITABLE:
            return {"error": f"{wf['actions']['label']} is not editable"}
        updates = {f["selector"]: f for f in fields if isinstance(f, dict)
                   and f.get("selector")}
        for f in record.get("fields", []):
            upd = updates.get(f["selector"])
            if upd is not None:
                f["value"] = str(upd.get("value") or "")
                f["needs_you"] = bool(upd.get("needs_you", False))
        record["updated_at"] = self._now()
        await self._db.put(self._coll(wf), key, record)
        return record

    # ---------- approval ----------

    async def approve(self, wf: dict, key: str, approved_by: str) -> dict | None:
        record = await self.get(wf, key)
        if record is None:
            return None
        if record.get("status") not in EDITABLE:
            return {"error": f"{wf['actions']['label']} cannot be approved "
                             "from its current status"}
        if any(f.get("needs_you") for f in record.get("fields", [])):
            return {"error": "resolve NEEDS-YOU fields before approving"}
        record["status"] = "approved"
        record["approval"] = {"approved_by": approved_by, "approved_at": self._now(),
                              "payload_hash": payload_hash(record["fields"])}
        await self._db.put(self._coll(wf), key, record)
        await self._audit(wf, "approve", key,
                          payload_hash=record["approval"]["payload_hash"])
        return record

    async def reject(self, wf: dict, key: str, comment: str) -> dict | None:
        record = await self.get(wf, key)
        if record is None:
            return None
        if not (comment or "").strip():
            return {"error": "a rejection comment is required"}
        if record.get("status") not in (EDITABLE | {"approved"}):
            return {"error": f"{wf['actions']['label']} cannot be rejected "
                             "from its current status"}
        record["status"] = "rejected"
        record["rejected_comment"] = comment.strip()
        record["rejected_at"] = self._now()
        record.pop("approval", None)
        await self._db.put(self._coll(wf), key, record)
        await self._audit(wf, "reject", key, comment=comment.strip())
        return record

    # ---------- execution ----------

    async def _sibling_conflict(self, wf: dict, record: dict) -> str | None:
        """Under the claim lock: block on a sibling of the same item that is
        already executed (or legacy 'submitted'), or that is currently
        in-flight ('executing') or ambiguous ('possibly_executed'). The
        in-flight/ambiguous check closes the race where a sibling claims the
        lock, releases it while its executor runs, and a second sibling
        passes the old executed-only check before the first one lands."""
        irf = self._irf(wf)
        siblings = await self._db.query(self._coll(wf), where={irf: record[irf]})
        me = record.get(self._kf(wf))
        label = wf["actions"]["label"]
        for s in siblings:
            if s.get(self._kf(wf)) == me:
                continue
            status = s.get("status")
            if status in ("executed", "submitted"):
                return (f"{wf['items']['label']} already has "
                        f"an executed {label}")
            if status in ("executing", "possibly_executed"):
                return (f"{wf['items']['label']} has "
                        f"a {label} awaiting completion or confirmation")
        return None

    async def _supersede_siblings(self, wf: dict, record: dict) -> None:
        irf, kf = self._irf(wf), self._kf(wf)
        siblings = await self._db.query(self._coll(wf), where={irf: record[irf]})
        for s in siblings:
            if s.get(kf) != record.get(kf) and s.get("status") in SUPERSEDABLE:
                s["status"] = "superseded"
                await self._db.put(self._coll(wf), s[kf], s)
                await self._audit(wf, "superseded", s[kf], actor="system")

    async def execute(self, wf: dict, key: str) -> dict | None:
        label = wf["actions"]["label"]
        async with self._exec_lock:
            record = await self.get(wf, key)
            if record is None:
                return None
            status = record.get("status")
            if status == "executed":
                return {"error": "already executed"}
            if status != "approved":
                return {"error": f"{label} not approved"}
            pinned = (record.get("approval") or {}).get("payload_hash")
            if payload_hash(record.get("fields", [])) != pinned:
                return {"error": "draft changed since approval; re-approve required"}
            conflict = await self._sibling_conflict(wf, record)
            if conflict:
                return {"error": conflict}
            executor = self._plugins.executor(wf["actions"]["executor"])
            pre = getattr(executor, "precondition", None)
            if pre is not None:
                msg = await pre(record)
                if msg:
                    return {"error": f"precondition failed: {msg}"}
            # Claim: the only writer that can move approved -> executing, and
            # it happens under the lock, before the external call.
            record["status"] = "executing"
            await self._db.put(self._coll(wf), key, record)
            await self._audit(wf, "claim", key)

        kf, irf = self._kf(wf), self._irf(wf)
        item_ref = record.get(irf)
        created_at, updated_at = record.get("created_at"), record.get("updated_at")
        try:
            updates = await executor.execute(record)
        except ExecutionFailed as e:
            # An executor can mutate the record in place (it's passed by
            # reference) before raising; re-force identity so a failing
            # executor can never hijack lineage.
            record[kf] = key
            record[irf] = item_ref
            record["status"] = "failed"
            self._append_note(record, f"execute failed: {e}")
            await self._db.put(self._coll(wf), key, record)
            await self._audit(wf, "execute-failed", key)
            return record
        except Exception as e:  # ExecutionAmbiguous or anything unexpected:
            # we cannot know whether the side effect landed, so never allow a
            # silent retry — a human must confirm.
            record[kf] = key
            record[irf] = item_ref
            record["status"] = "possibly_executed"
            self._append_note(record, f"outcome unknown: {type(e).__name__}: {e} — "
                                      "verify externally before confirming")
            await self._db.put(self._coll(wf), key, record)
            await self._audit(wf, "execute-ambiguous", key)
            return record

        try:
            record.update(updates or {})
            record[kf] = key
            record[irf] = item_ref
            record["status"] = "executed"
            record["executed_at"] = self._now()
            record["created_at"] = created_at
            record["updated_at"] = updated_at
            await self._db.put(self._coll(wf), key, record)
            await self._audit(wf, "execute", key)
            await self._supersede_siblings(wf, record)
            return record
        except Exception as e:
            # The external action may already have succeeded before this
            # failed (a buggy executor return value, a storage hiccup while
            # persisting, etc.) — we cannot know, so we never leave the
            # record stuck in "executing"; a human must confirm.
            record[kf] = key
            record[irf] = item_ref
            record["created_at"] = created_at
            record["updated_at"] = updated_at
            record["status"] = "possibly_executed"
            self._append_note(record, f"post-execution processing failed: {e}")
            await self._db.put(self._coll(wf), key, record)
            await self._audit(wf, "execute-ambiguous", key)
            return record

    async def confirm(self, wf: dict, key: str, outcome: str) -> dict | None:
        record = await self.get(wf, key)
        if record is None:
            return None
        if record.get("status") != "possibly_executed":
            return {"error": f"{wf['actions']['label']} is not awaiting confirmation"}
        if outcome not in ("executed", "failed"):
            return {"error": "outcome must be 'executed' or 'failed'"}
        record["status"] = outcome
        if outcome == "executed":
            record["executed_at"] = self._now()
        await self._db.put(self._coll(wf), key, record)
        await self._audit(wf, f"confirm-{outcome}", key)
        if outcome == "executed":
            await self._supersede_siblings(wf, record)
        return record

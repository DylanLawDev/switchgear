from __future__ import annotations

import logging
import time
from pathlib import Path

from switchgear.storage.base import Storage
from switchgear.workflows.model import WorkflowParseError, parse_workflow

COLLECTION = "workflows"

logger = logging.getLogger(__name__)


class WorkflowStore:
    def __init__(self, storage: Storage, *, generators: set[str], executors: set[str]):
        self._db = storage
        self._generators = generators
        self._executors = executors

    def validate(self, text: str) -> dict:
        return parse_workflow(text, generators=self._generators, executors=self._executors)

    async def save(self, text: str, source: str, status: str | None = None) -> dict:
        doc = parse_workflow(text, generators=self._generators, executors=self._executors)
        status = status or ("active" if source in {"repo", "owner"} else "pending")
        record = {**doc, "text": text, "status": status, "source": source,
                  "updated_at": time.time()}
        await self._db.put(COLLECTION, doc["name"], record)
        return record

    async def get(self, name: str) -> dict | None:
        return await self._db.get(COLLECTION, name)

    async def list(self) -> list[dict]:
        docs = await self._db.query(COLLECTION)
        docs.sort(key=lambda d: d["name"])
        return [{"name": d["name"], "description": d["description"],
                 "ui_home": d.get("ui_home", "workflows"),
                 "status": d["status"], "source": d["source"]} for d in docs]

    async def active_definitions(self) -> list[dict]:
        return [doc for doc in await self._db.query(COLLECTION)
                if doc.get("status") == "active"]

    @staticmethod
    def filter_expired_items(workflow: dict, records: list[dict],
                             now: float | None = None) -> list[dict]:
        if not workflow.get("items"):
            return records
        retention = workflow["items"].get("retention")
        if not retention:
            return records
        timestamp = next((name for name, field in workflow["items"]["fields"].items()
                          if field["type"] == "timestamp"), None)
        if timestamp is None:
            return records
        cutoff = (time.time() if now is None else now) - retention
        return [record for record in records
                if not isinstance(record.get(timestamp), (int, float))
                or record[timestamp] >= cutoff]

    async def purge_expired_items(self, workflow: dict) -> int:
        if not workflow.get("items"):
            return 0
        records = await self._db.query(workflow["items"]["collection"])
        kept = self.filter_expired_items(workflow, records)
        keep_ids = {record.get("_id") for record in kept}
        expired = [record for record in records if record.get("_id") not in keep_ids]
        key_field = workflow["items"]["key_field"]
        for record in expired:
            await self._db.delete(workflow["items"]["collection"], record.get(key_field))
        return len(expired)

    async def set_status(self, name: str, status: str) -> dict | None:
        doc = await self._db.get(COLLECTION, name)
        if doc is None:
            return None
        doc["status"] = status
        doc["updated_at"] = time.time()
        await self._db.put(COLLECTION, name, doc)
        return doc

    async def seed_dir(self, path: str) -> int:
        root = Path(path)
        if not root.exists():
            return 0
        count = 0
        for child in sorted(root.iterdir()):
            wf_file = child / "WORKFLOW.md"
            if not (child.is_dir() and wf_file.exists()):
                continue
            text = wf_file.read_text()
            try:
                doc = parse_workflow(text, generators=self._generators,
                                     executors=self._executors)
            except WorkflowParseError as e:
                logger.warning("skipping workflow %s: %s", wf_file, e)
                continue
            name = doc["name"]
            existing = await self.get(name)
            if existing is None:
                await self.save(text, source="repo")
                count += 1
            elif existing.get("source") == "repo" and existing.get("text") != text:
                record = {**existing, **doc, "text": text,
                          "status": existing["status"], "source": existing["source"],
                          "updated_at": time.time()}
                await self._db.put(COLLECTION, name, record)
                count += 1
        return count

"""ResourceStore: validated CRUD for owner-curated resources (spec §4).

Resources are agent-READ-ONLY: the only write paths are the owner UI/API
(source="user") and repo seeding (source="seed") — see security invariant 3.
Every write is audited to the `audit` collection.
"""

import csv
import io
import json
import logging
import re
import time
from pathlib import Path
from uuid import uuid4

import yaml

from switchgear.career.bank import CareerBank, CareerBankError, from_dict, load_bank
from switchgear.config import Settings
from switchgear.storage.base import Storage

logger = logging.getLogger(__name__)

COLLECTION = "resources"
KINDS = {"csv", "json", "md", "txt"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
RESERVED_NAMES = {"settings", "pending"}


class ResourceError(Exception):
    pass


def _validate_content(name: str, kind: str, content: str) -> None:
    if kind == "json":
        try:
            json.loads(content)
        except ValueError as e:
            raise ResourceError(f"{name}: content is not valid json: {e}") from None
    elif kind == "csv":
        rows = list(csv.reader(io.StringIO(content)))
        if not rows:
            raise ResourceError(f"{name}: csv needs a header row")
        width = len(rows[0])
        for i, row in enumerate(rows[1:], start=2):
            if len(row) != width:
                raise ResourceError(
                    f"{name}: csv row {i} has {len(row)} columns, header has {width}")


class ResourceStore:
    def __init__(self, storage: Storage, settings: Settings):
        self._db = storage
        self._s = settings

    async def _audit(self, action: str, name: str) -> None:
        await self._db.put("audit", f"resource-{uuid4().hex}", {
            "action": action, "name": name, "at": time.time()})

    async def validate(self, name: str, kind: str, content: str) -> dict | None:
        """Run save()'s checks without writing. Returns the existing doc or None."""
        if not NAME_RE.fullmatch(str(name or "")):
            raise ResourceError(
                f"invalid name {name!r} (must match ^[a-z0-9][a-z0-9-]{{1,63}}$)")
        if name in RESERVED_NAMES:
            raise ResourceError(f"{name}: reserved name")
        if kind not in KINDS:
            raise ResourceError(f"{name}: unknown kind {kind!r} (use csv, json, md, txt)")
        size = len(content.encode())
        if size > self._s.resource_max_bytes:
            raise ResourceError(
                f"{name}: {size} bytes exceeds the "
                f"{self._s.resource_max_bytes}-byte limit")
        _validate_content(name, kind, content)
        existing = await self._db.get(COLLECTION, name)
        if existing is not None and existing.get("kind") != kind:
            raise ResourceError(
                f"{name}: kind is immutable (stored {existing.get('kind')!r}, got "
                f"{kind!r} — delete and recreate to change)")
        return existing

    async def save(self, name: str, kind: str, description: str, content: str,
                   source: str = "user") -> dict:
        existing = await self.validate(name, kind, content)
        size = len(content.encode())
        now = time.time()
        doc = {
            "name": name,
            "kind": kind,
            "description": str(description or ""),
            "content": content,
            "size": size,
            "source": source,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        await self._db.put(COLLECTION, name, doc)
        await self._audit("resource_save", name)
        return doc

    async def get(self, name: str) -> dict | None:
        return await self._db.get(COLLECTION, name)

    async def list(self) -> list[dict]:
        docs = await self._db.query(COLLECTION)
        good = []
        for d in docs:
            if "name" not in d or "kind" not in d:
                logger.warning("skipping malformed resource doc %r: missing name/kind",
                               d.get("_id", d))
                continue
            good.append(d)
        good.sort(key=lambda d: d["name"])
        return [{"name": d["name"], "kind": d["kind"],
                 "description": d.get("description", ""), "size": d.get("size", 0),
                 "source": d.get("source", "unknown"),
                 "updated_at": d.get("updated_at", 0.0)}
                for d in good]

    async def delete(self, name: str) -> bool:
        if await self._db.get(COLLECTION, name) is None:
            return False
        await self._db.delete(COLLECTION, name)
        await self._audit("resource_delete", name)
        return True

    async def seed_dir(self, path: str) -> int:
        """Seed repo files into the store. `<name>.<kind>` (+ optional
        `<name>.meta.yaml` carrying `description`): insert if missing, update
        while the doc is still seed-sourced, never touch user-edited docs."""
        root = Path(path)
        if not root.is_dir():
            return 0
        count = 0
        for file in sorted(root.iterdir()):
            kind = file.suffix.lstrip(".")
            if not file.is_file() or kind not in KINDS:
                continue
            name = file.stem
            try:
                content = file.read_text()
            except (OSError, UnicodeDecodeError) as e:
                logger.warning("skipping unreadable resource seed %s: %s", file, e)
                continue
            existing = await self.get(name)
            if existing is not None and (
                existing.get("source") != "seed" or existing.get("content") == content
            ):
                continue
            description = ""
            meta_file = root / f"{name}.meta.yaml"
            if meta_file.exists():
                try:
                    meta = yaml.safe_load(meta_file.read_text()) or {}
                except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
                    logger.warning("bad resource meta %s: %s", meta_file, e)
                    meta = {}
                if not isinstance(meta, dict):
                    logger.warning("bad resource meta %s: not a mapping", meta_file)
                    meta = {}
                description = str(meta.get("description") or "")
            if not description and existing is not None:
                description = existing.get("description", "")
            try:
                await self.save(name, kind, description, content, source="seed")
                count += 1
            except ResourceError as e:
                logger.warning("skipping resource %s: %s", file, e)
        return count


def make_bank_provider(store: ResourceStore, settings: Settings):
    """Async accessor for the current CareerBank, or None if unavailable.

    Parses the `career-bank` resource, caching the parsed bank keyed on the
    resource's updated_at so UI edits take effect without restart. An invalid
    resource logs and yields None (the owner should fix the resource, not get
    silently stale data). Only when the resource is ABSENT does it fall back
    to load_bank(settings.career_dir), computed once and cached; a broken
    career/ dir logs a warning and yields None.
    """
    cache: dict = {"updated_at": None, "bank": None}
    fallback: dict = {}

    async def bank_provider() -> CareerBank | None:
        doc = await store.get("career-bank")
        if doc is not None:
            if doc["updated_at"] != cache["updated_at"]:
                try:
                    bank = from_dict(json.loads(doc["content"]))
                except (ValueError, CareerBankError) as e:
                    logger.warning("career-bank resource is invalid: %s", e)
                    bank = None
                cache["updated_at"] = doc["updated_at"]
                cache["bank"] = bank
            return cache["bank"]
        if "bank" not in fallback:
            try:
                fallback["bank"] = load_bank(settings.career_dir)
            except CareerBankError as e:
                logger.warning("career bank not loaded (%s): %s",
                               settings.career_dir, e)
                fallback["bank"] = None
        return fallback["bank"]

    return bank_provider

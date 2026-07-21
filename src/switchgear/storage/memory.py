import asyncio
import copy
import json
from pathlib import Path

from switchgear.storage.base import Storage


class MemoryStorage(Storage):
    def __init__(self, path: str | None = None):
        self._path = Path(path) if path else None
        self._data: dict[str, dict[str, dict]] = {}
        self._lock = asyncio.Lock()
        if self._path and self._path.exists():
            self._data = json.loads(self._path.read_text())

    def _flush(self) -> None:
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data))

    async def get(self, collection: str, key: str) -> dict | None:
        doc = self._data.get(collection, {}).get(key)
        return copy.deepcopy(doc) if doc is not None else None

    async def put(self, collection: str, key: str, doc: dict) -> None:
        self._data.setdefault(collection, {})[key] = copy.deepcopy(doc)
        self._flush()

    async def delete(self, collection: str, key: str) -> None:
        self._data.get(collection, {}).pop(key, None)
        self._flush()

    async def query(
        self, collection: str, where: dict | None = None, limit: int | None = None
    ) -> list[dict]:
        out = []
        for key, doc in self._data.get(collection, {}).items():
            if where and any(doc.get(f) != v for f, v in where.items()):
                continue
            out.append({**doc, "_id": key})
            if limit and len(out) >= limit:
                break
        return out

    async def compare_and_set(self, collection: str, key: str, expected: dict,
                              updates: dict) -> dict | None:
        async with self._lock:
            doc = self._data.get(collection, {}).get(key)
            if doc is None or any(doc.get(field) != value
                                  for field, value in expected.items()):
                return None
            merged = {**doc, **copy.deepcopy(updates)}
            self._data.setdefault(collection, {})[key] = merged
            self._flush()
            return copy.deepcopy(merged)

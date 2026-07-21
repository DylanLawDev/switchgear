import asyncio
from contextlib import asynccontextmanager

from switchgear.storage.base import Storage


class LiveUpdates:
    """In-process fan-out for UI cache invalidation events."""

    def __init__(self):
        self._subscribers: set[asyncio.Queue[str]] = set()

    def publish(self, topic: str) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - defensive race guard
                    pass
            queue.put_nowait(topic)

    @asynccontextmanager
    async def subscribe(self):
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)


class NotifyingStorage(Storage):
    """Storage adapter that announces mutations made through this app process."""

    def __init__(self, inner: Storage, updates: LiveUpdates):
        self._inner = inner
        self._updates = updates

    async def get(self, collection: str, key: str) -> dict | None:
        return await self._inner.get(collection, key)

    async def put(self, collection: str, key: str, doc: dict) -> None:
        await self._inner.put(collection, key, doc)
        self._updates.publish(collection)

    async def delete(self, collection: str, key: str) -> None:
        await self._inner.delete(collection, key)
        self._updates.publish(collection)

    async def query(self, collection: str, where: dict | None = None,
                    limit: int | None = None) -> list[dict]:
        return await self._inner.query(collection, where=where, limit=limit)

    async def compare_and_set(self, collection: str, key: str, expected: dict,
                              updates: dict) -> dict | None:
        result = await self._inner.compare_and_set(collection, key, expected, updates)
        if result is not None:
            self._updates.publish(collection)
        return result

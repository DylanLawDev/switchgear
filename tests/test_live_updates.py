import asyncio

import pytest

from switchgear.chat_runs import ChatRunManager
from switchgear.live import LiveUpdates, NotifyingStorage
from switchgear.storage.memory import MemoryStorage

pytestmark = pytest.mark.asyncio


async def test_chat_run_continues_after_viewer_disconnects():
    manager = ChatRunManager()
    released = asyncio.Event()

    async def worker(run):
        await run.publish({"type": "text", "delta": "first"})
        await released.wait()
        await run.publish({"type": "text", "delta": " second"})
        await run.finish()

    run = manager.start("c1", worker)
    viewer = run.stream()
    assert "first" in await anext(viewer)
    await viewer.aclose()

    released.set()
    await run.task
    assert [event["delta"] for event in run.events] == ["first", " second"]


async def test_notifying_storage_publishes_collection_mutations():
    updates = LiveUpdates()
    storage = NotifyingStorage(MemoryStorage(), updates)
    async with updates.subscribe() as queue:
        await storage.put("resources", "one", {"content": "x"})
        assert await queue.get() == "resources"
        await storage.delete("resources", "one")
        assert await queue.get() == "resources"

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable


class ChatRun:
    """A server-owned chat run whose lifetime is independent of an HTTP viewer."""

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.events: list[dict] = []
        self.done = False
        self._changed = asyncio.Condition()
        self.task: asyncio.Task | None = None

    async def publish(self, event: dict) -> None:
        async with self._changed:
            self.events.append(event)
            self._changed.notify_all()

    async def finish(self) -> None:
        async with self._changed:
            self.done = True
            self._changed.notify_all()

    async def stream(self) -> AsyncIterator[str]:
        index = 0
        while True:
            async with self._changed:
                await self._changed.wait_for(lambda: index < len(self.events) or self.done)
                pending = self.events[index:]
                index = len(self.events)
                done = self.done
            for event in pending:
                yield f"data: {json.dumps(event)}\n\n"
            if done and index == len(self.events):
                return


class ChatRunManager:
    def __init__(self):
        self._runs: dict[str, ChatRun] = {}

    def active(self, conversation_id: str) -> bool:
        run = self._runs.get(conversation_id)
        return bool(run and run.task and not run.task.done())

    def start(self, conversation_id: str,
              worker: Callable[[ChatRun], Awaitable[None]]) -> ChatRun:
        if self.active(conversation_id):
            raise RuntimeError("conversation already has an active run")
        run = ChatRun(conversation_id)
        run.task = asyncio.create_task(worker(run))
        self._runs[conversation_id] = run
        return run

    async def shutdown(self) -> None:
        tasks = [run.task for run in self._runs.values()
                 if run.task is not None and not run.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

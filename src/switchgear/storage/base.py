from abc import ABC, abstractmethod


class Storage(ABC):
    @abstractmethod
    async def get(self, collection: str, key: str) -> dict | None: ...

    @abstractmethod
    async def put(self, collection: str, key: str, doc: dict) -> None: ...

    @abstractmethod
    async def delete(self, collection: str, key: str) -> None: ...

    @abstractmethod
    async def query(
        self, collection: str, where: dict | None = None, limit: int | None = None
    ) -> list[dict]: ...

    @abstractmethod
    async def compare_and_set(
        self, collection: str, key: str, expected: dict, updates: dict
    ) -> dict | None:
        """Atomically update a document when all expected fields still match."""
        ...

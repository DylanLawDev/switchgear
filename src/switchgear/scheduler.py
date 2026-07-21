import time
from abc import ABC, abstractmethod

from switchgear.config import Settings
from switchgear.storage.base import Storage

COLLECTION = "schedules"


def _is_not_found(exc: Exception) -> bool:
    # google.api_core.exceptions.NotFound has __name__ == "NotFound";
    # matching by name avoids a hard google dependency in the offline path.
    return type(exc).__name__ == "NotFound"


class Scheduler(ABC):
    @abstractmethod
    async def create(self, name: str, cron: str, skill: str,
                     path: str | None = None,
                     timezone: str = "Etc/UTC") -> dict: ...

    @abstractmethod
    async def delete(self, name: str) -> None: ...

    @abstractmethod
    async def list(self) -> list[dict]: ...


class LocalScheduler(Scheduler):
    def __init__(self, storage: Storage, settings: Settings):
        self._db = storage
        self._s = settings

    def _target(self, skill: str, path: str | None = None) -> str:
        return self._s.service_url.rstrip("/") + (path or f"/tasks/run-skill/{skill}")

    async def create(self, name: str, cron: str, skill: str,
                     path: str | None = None,
                     timezone: str = "Etc/UTC") -> dict:
        doc = {"skill": skill, "cron": cron, "target_url": self._target(skill, path),
               "enabled": True, "updated_at": time.time()}
        await self._db.put(COLLECTION, name, doc)
        return doc

    async def delete(self, name: str) -> None:
        await self._db.delete(COLLECTION, name)

    async def list(self) -> list[dict]:
        docs = await self._db.query(COLLECTION)
        docs.sort(key=lambda d: d.get("skill", ""))
        return [{"skill": d["skill"], "cron": d["cron"],
                 "enabled": d.get("enabled", True),
                 "target_url": d.get("target_url", "")} for d in docs]


class CloudScheduler(Scheduler):
    def __init__(self, storage: Storage, settings: Settings, client=None, sched=None):
        self._local = LocalScheduler(storage, settings)
        self._s = settings
        self._client = client
        self._sched = sched

    def _ensure(self) -> None:
        if self._client is None or self._sched is None:
            from google.cloud import scheduler_v1

            self._sched = self._sched or scheduler_v1
            self._client = self._client or scheduler_v1.CloudSchedulerClient()

    def _parent(self) -> str:
        return f"projects/{self._s.gcp_project}/locations/{self._s.gcp_region}"

    def _job_name(self, skill: str) -> str:
        return f"{self._parent()}/jobs/switchgear-{skill}"

    async def create(self, name: str, cron: str, skill: str,
                     path: str | None = None,
                     timezone: str = "Etc/UTC") -> dict:
        self._ensure()
        doc = await self._local.create(name, cron, skill, path)
        job = {
            "name": self._job_name(skill),
            "schedule": cron,
            "time_zone": timezone,
            "http_target": {
                "uri": doc["target_url"],
                "http_method": self._sched.HttpMethod.POST,
                "headers": {"X-Cron-Secret": self._s.cron_secret},
            },
        }
        try:
            self._client.delete_job(name=job["name"])
        except Exception as e:
            if not _is_not_found(e):
                raise
        self._client.create_job(parent=self._parent(), job=job)
        return doc

    async def delete(self, name: str) -> None:
        self._ensure()
        try:
            self._client.delete_job(name=self._job_name(name))
        except Exception as e:
            if not _is_not_found(e):
                raise
        await self._local.delete(name)

    async def list(self) -> list[dict]:
        return await self._local.list()

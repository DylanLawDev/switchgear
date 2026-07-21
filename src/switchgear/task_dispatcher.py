import asyncio
from datetime import datetime, timezone


class TaskDispatcher:
    cloud = False

    async def enqueue_run(self, run_id: str, step_index: int) -> None:
        return None

    async def replace_once(self, schedule_id: str, run_at: str) -> None:
        return None

    async def delete_once(self, schedule_id: str) -> None:
        return None


class CloudTaskDispatcher(TaskDispatcher):
    cloud = True

    def __init__(self, settings, client=None, tasks_module=None):
        self._settings = settings
        self._client = client
        self._tasks = tasks_module

    def _ensure(self):
        if self._client is None or self._tasks is None:
            from google.cloud import tasks_v2

            self._tasks = self._tasks or tasks_v2
            self._client = self._client or tasks_v2.CloudTasksClient()

    def _parent(self) -> str:
        return self._client.queue_path(self._settings.gcp_project,
                                       self._settings.gcp_region,
                                       self._settings.task_queue)

    def _http_task(self, uri: str) -> dict:
        return {"http_request": {"http_method": self._tasks.HttpMethod.POST,
                                 "url": uri,
                                 "headers": {
                                     "X-Cron-Secret": self._settings.cron_secret}}}

    async def enqueue_run(self, run_id: str, step_index: int) -> None:
        self._ensure()
        task = self._http_task(
            f"{self._settings.service_url.rstrip('/')}/tasks/workflow-runs/"
            f"{run_id}/advance?step={step_index}")
        task["name"] = self._client.task_path(
            self._settings.gcp_project, self._settings.gcp_region,
            self._settings.task_queue, f"{run_id}-{step_index}")
        await asyncio.to_thread(self._client.create_task,
                                request={"parent": self._parent(), "task": task})

    async def replace_once(self, schedule_id: str, run_at: str) -> None:
        self._ensure()
        task_name = self._client.task_path(
            self._settings.gcp_project, self._settings.gcp_region,
            self._settings.task_queue, f"once-{schedule_id}")
        try:
            await asyncio.to_thread(self._client.delete_task, request={"name": task_name})
        except Exception as exc:
            if type(exc).__name__ != "NotFound":
                raise
        task = self._http_task(
            f"{self._settings.service_url.rstrip('/')}/tasks/schedules/{schedule_id}/fire")
        task["name"] = task_name
        when = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        from google.protobuf.timestamp_pb2 import Timestamp

        stamp = Timestamp()
        stamp.FromDatetime(when)
        task["schedule_time"] = stamp
        await asyncio.to_thread(self._client.create_task,
                                request={"parent": self._parent(), "task": task})

    async def delete_once(self, schedule_id: str) -> None:
        self._ensure()
        task_name = self._client.task_path(
            self._settings.gcp_project, self._settings.gcp_region,
            self._settings.task_queue, f"once-{schedule_id}")
        try:
            await asyncio.to_thread(self._client.delete_task,
                                    request={"name": task_name})
        except Exception as exc:
            if type(exc).__name__ != "NotFound":
                raise

import pytest

from switchgear.config import Settings
from switchgear.scheduler import CloudScheduler, LocalScheduler
from switchgear.storage.memory import MemoryStorage

S = Settings(_env_file=None, service_url="https://agent.example.com",
             gcp_project="proj", gcp_region="us-central1",
             cron_secret="topsecret")


async def test_local_create_list_delete():
    sch = LocalScheduler(MemoryStorage(), S)
    doc = await sch.create(name="job-search", cron="0 9 * * *", skill="job-search")
    assert doc["target_url"] == "https://agent.example.com/tasks/run-skill/job-search"
    assert await sch.list() == [{
        "skill": "job-search", "cron": "0 9 * * *", "enabled": True,
        "target_url": "https://agent.example.com/tasks/run-skill/job-search"}]
    await sch.delete("job-search")
    assert await sch.list() == []


class FakeMethod:
    POST = "POST"


class FakeSched:
    HttpMethod = FakeMethod


class FakeClient:
    def __init__(self):
        self.created = []
        self.deleted = []

    def create_job(self, parent, job):
        self.created.append((parent, job))

    def delete_job(self, name):
        self.deleted.append(name)


async def test_cloud_create_provisions_secret_authenticated_job_and_mirrors():
    client = FakeClient()
    sch = CloudScheduler(MemoryStorage(), S, client=client, sched=FakeSched())
    await sch.create(name="job-search", cron="0 9 * * *", skill="job-search")
    # mirrored to storage for the dashboard
    assert (await sch.list())[0]["skill"] == "job-search"
    parent, job = client.created[0]
    assert parent == "projects/proj/locations/us-central1"
    assert job["name"] == "projects/proj/locations/us-central1/jobs/switchgear-job-search"
    assert job["schedule"] == "0 9 * * *"
    tgt = job["http_target"]
    assert tgt["uri"] == "https://agent.example.com/tasks/run-skill/job-search"
    assert tgt["http_method"] == "POST"
    assert tgt["headers"] == {"X-Cron-Secret": "topsecret"}


async def test_cloud_secret_header_matches_cron_verifier():
    client = FakeClient()
    sch = CloudScheduler(MemoryStorage(), S, client=client, sched=FakeSched())
    await sch.create(name="job-search", cron="0 9 * * *", skill="job-search")
    _, job = client.created[0]
    assert job["http_target"]["headers"]["X-Cron-Secret"] == S.cron_secret


async def test_cloud_delete_removes_job_and_mirror():
    client = FakeClient()
    sch = CloudScheduler(MemoryStorage(), S, client=client, sched=FakeSched())
    await sch.create(name="job-search", cron="0 9 * * *", skill="job-search")
    await sch.delete("job-search")
    assert client.deleted[-1] == "projects/proj/locations/us-central1/jobs/switchgear-job-search"
    assert await sch.list() == []


class NotFound(Exception):
    pass


class PermissionDenied(Exception):
    pass


class RaisingDeleteClient(FakeClient):
    def __init__(self, exc_cls):
        super().__init__()
        self._exc_cls = exc_cls

    def delete_job(self, name):
        raise self._exc_cls(name)


async def test_cloud_delete_swallows_not_found_and_removes_mirror():
    client = FakeClient()
    sch = CloudScheduler(MemoryStorage(), S, client=client, sched=FakeSched())
    await sch.create(name="job-search", cron="0 9 * * *", skill="job-search")
    sch._client = RaisingDeleteClient(NotFound)
    await sch.delete("job-search")
    assert await sch.list() == []


async def test_cloud_delete_reraises_non_not_found_and_keeps_mirror():
    client = FakeClient()
    sch = CloudScheduler(MemoryStorage(), S, client=client, sched=FakeSched())
    await sch.create(name="job-search", cron="0 9 * * *", skill="job-search")
    sch._client = RaisingDeleteClient(PermissionDenied)
    with pytest.raises(PermissionDenied):
        await sch.delete("job-search")
    assert (await sch.list())[0]["skill"] == "job-search"


# ---------- custom target paths (channel polling) ----------


async def test_local_create_with_path_targets_custom_endpoint():
    sch = LocalScheduler(MemoryStorage(), S)
    doc = await sch.create(name="poll-email", cron="*/5 * * * *",
                           skill="poll-email", path="/tasks/poll-channel/email")
    assert doc["target_url"] == "https://agent.example.com/tasks/poll-channel/email"
    assert (await sch.list())[0] == {
        "skill": "poll-email", "cron": "*/5 * * * *", "enabled": True,
        "target_url": "https://agent.example.com/tasks/poll-channel/email"}


async def test_local_create_without_path_keeps_run_skill_target():
    sch = LocalScheduler(MemoryStorage(), S)
    doc = await sch.create(name="job-search", cron="0 9 * * *", skill="job-search")
    assert doc["target_url"] == "https://agent.example.com/tasks/run-skill/job-search"


async def test_cloud_create_with_path_targets_custom_endpoint():
    client = FakeClient()
    sch = CloudScheduler(MemoryStorage(), S, client=client, sched=FakeSched())
    await sch.create(name="poll-email", cron="*/5 * * * *", skill="poll-email",
                     path="/tasks/poll-channel/email")
    _, job = client.created[0]
    assert job["name"].endswith("/jobs/switchgear-poll-email")
    assert job["schedule"] == "*/5 * * * *"
    tgt = job["http_target"]
    assert tgt["uri"] == "https://agent.example.com/tasks/poll-channel/email"
    assert tgt["headers"]["X-Cron-Secret"] == S.cron_secret

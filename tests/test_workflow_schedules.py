import asyncio

import pytest

from switchgear.storage.memory import MemoryStorage
from switchgear.workflow_schedules import WorkflowScheduleService


class WorkflowStore:
    async def get(self, name):
        if name != "daily-flow":
            return None
        return {"name": name, "status": "active",
                "execution": {"inputs": {"type": "object"}}}


class Runner:
    def __init__(self):
        self.runs = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.delay = False
        self.start_error = False
        self.dispatch_error = False

    async def list(self, schedule_id=None, **kwargs):
        return [run for run in self.runs if run.get("schedule_id") == schedule_id]

    async def start(self, workflow, inputs, *, trigger, schedule_id):
        if self.start_error:
            raise ValueError("invalid inputs")
        if self.delay:
            self.started.set()
            await self.release.wait()
        run = {"id": f"run-{len(self.runs)}", "workflow": workflow,
               "inputs": inputs, "trigger": trigger, "schedule_id": schedule_id,
               "status": "queued"}
        self.runs.append(run)
        return run

    async def dispatch(self, run_id):
        if self.dispatch_error:
            raise RuntimeError("dispatch unavailable")
        return next(run for run in self.runs if run["id"] == run_id)


class Agents:
    async def run(self, prompt, **kwargs):
        return {"id": "resolver-1", "ok": True, "output": {"resolved": prompt},
                "error": None}


class Scheduler:
    def __init__(self):
        self.jobs = {}

    async def create(self, name, cron, skill, path=None, timezone="Etc/UTC"):
        self.jobs[name] = {"cron": cron, "skill": skill, "path": path,
                           "timezone": timezone}

    async def delete(self, name):
        self.jobs.pop(name, None)


class Dispatcher:
    cloud = False


def body(mode="direct"):
    return {"name": "Daily", "workflow": "daily-flow", "enabled": True,
            "trigger": {"kind": "cron", "cron": "0 9 * * *",
                        "timezone": "America/Los_Angeles"},
            "input": ({"mode": "direct", "values": {"region": "west"}}
                      if mode == "direct" else
                      {"mode": "prompt", "prompt": "Find today's input"}),
            "allow_overlap": False}


async def test_schedule_crud_and_prompt_resolution():
    db, runner, scheduler = MemoryStorage(), Runner(), Scheduler()
    service = WorkflowScheduleService(db, scheduler, WorkflowStore(), runner,
                                      Agents(), Dispatcher())
    schedule = await service.save(body("prompt"), source="owner")
    assert schedule["id"] in scheduler.jobs
    result = await service.fire(schedule["id"], trigger="manual")
    assert result["resolver_run_id"] == "resolver-1"
    assert result["run"]["inputs"] == {"resolved": "Find today's input"}
    assert await service.delete(schedule["id"]) is True
    assert schedule["id"] not in scheduler.jobs


async def test_schedule_claim_closes_concurrent_overlap_race():
    db, runner = MemoryStorage(), Runner()
    runner.delay = True
    service = WorkflowScheduleService(db, Scheduler(), WorkflowStore(), runner,
                                      Agents(), Dispatcher())
    schedule = await service.save(body())
    first = asyncio.create_task(service.fire(schedule["id"]))
    await runner.started.wait()
    second = await service.fire(schedule["id"])
    assert second["skipped"] is True and second["reason"] == "schedule is firing"
    runner.release.set()
    assert (await first)["ok"] is True


@pytest.mark.parametrize("failure", ["start_error", "dispatch_error"])
async def test_schedule_releases_fire_claim_when_run_startup_fails(failure):
    db, runner = MemoryStorage(), Runner()
    setattr(runner, failure, True)
    service = WorkflowScheduleService(db, Scheduler(), WorkflowStore(), runner,
                                      Agents(), Dispatcher())
    schedule = await service.save(body())

    with pytest.raises((ValueError, RuntimeError)):
        await service.fire(schedule["id"])

    stored = await service.get(schedule["id"])
    assert stored["fire_claim"] is None
    assert stored["fire_claim_until"] == 0.0

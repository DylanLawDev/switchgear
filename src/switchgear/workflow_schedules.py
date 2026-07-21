from __future__ import annotations

import time
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

COLLECTION = "workflow-schedules"


class ScheduleError(Exception):
    pass


class WorkflowScheduleService:
    def __init__(self, storage, scheduler, workflow_store, workflow_runner, agent_runner,
                 dispatcher=None):
        self._db = storage
        self._scheduler = scheduler
        self._workflows = workflow_store
        self._runs = workflow_runner
        self._agents = agent_runner
        self._dispatcher = dispatcher

    async def _validate(self, body: dict, schedule_id: str | None = None) -> dict:
        name = str(body.get("name") or "").strip()
        workflow_name = str(body.get("workflow") or "")
        workflow = await self._workflows.get(workflow_name)
        if not name:
            raise ScheduleError("name is required")
        if workflow is None or workflow.get("status") != "active" or not workflow.get("execution"):
            raise ScheduleError("workflow must be active and executable")
        trigger = body.get("trigger")
        if not isinstance(trigger, dict) or trigger.get("kind") not in {"cron", "once"}:
            raise ScheduleError("trigger.kind must be cron or once")
        timezone = str(trigger.get("timezone") or "Etc/UTC")
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            raise ScheduleError("timezone must be a valid IANA timezone") from None
        if trigger["kind"] == "cron":
            expression = str(trigger.get("cron") or "")
            if not croniter.is_valid(expression):
                raise ScheduleError("invalid cron expression")
            clean_trigger = {"kind": "cron", "cron": expression, "timezone": timezone}
            next_run_at = croniter(expression, datetime.now(zone)).get_next(datetime).timestamp()
        else:
            run_at = str(trigger.get("run_at") or "")
            try:
                when = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
            except ValueError:
                raise ScheduleError("run_at must be an ISO timestamp") from None
            if when.tzinfo is None:
                when = when.replace(tzinfo=zone)
            clean_trigger = {"kind": "once", "run_at": when.isoformat(),
                             "timezone": timezone}
            next_run_at = when.timestamp()
        input_spec = body.get("input")
        if not isinstance(input_spec, dict) or input_spec.get("mode") not in {"direct", "prompt"}:
            raise ScheduleError("input.mode must be direct or prompt")
        if input_spec["mode"] == "direct":
            if not isinstance(input_spec.get("values", {}), dict):
                raise ScheduleError("direct input values must be an object")
            clean_input = {"mode": "direct", "values": input_spec.get("values", {})}
        else:
            if not str(input_spec.get("prompt") or "").strip():
                raise ScheduleError("prompt input requires a prompt")
            clean_input = {"mode": "prompt", "prompt": str(input_spec["prompt"]),
                           "resolver_agent": str(input_spec.get("resolver_agent") or "")}
        return {"id": schedule_id or f"sch-{uuid4().hex[:16]}", "name": name,
                "workflow": workflow_name, "enabled": bool(body.get("enabled", True)),
                "trigger": clean_trigger, "input": clean_input,
                "allow_overlap": bool(body.get("allow_overlap", False)),
                "next_run_at": next_run_at,
                "fire_claim": None, "fire_claim_until": 0.0}

    async def save(self, body: dict, schedule_id: str | None = None,
                   source: str = "owner") -> dict:
        existing = await self.get(schedule_id) if schedule_id else None
        doc = await self._validate(body, schedule_id=schedule_id)
        now = time.time()
        doc.update({"source": source, "created_at": (existing or {}).get("created_at", now),
                    "updated_at": now, "last_run_at": (existing or {}).get("last_run_at"),
                    "fire_claim": (existing or {}).get("fire_claim"),
                    "fire_claim_until": (existing or {}).get("fire_claim_until", 0.0)})
        if existing and existing.get("trigger", {}).get("kind") == "cron":
            await self._scheduler.delete(schedule_id)
        elif (existing and existing.get("trigger", {}).get("kind") == "once"
              and self._dispatcher is not None and self._dispatcher.cloud):
            await self._dispatcher.delete_once(schedule_id)
        await self._db.put(COLLECTION, doc["id"], doc)
        if doc["enabled"] and doc["trigger"]["kind"] == "cron":
            await self._scheduler.create(
                name=doc["id"], cron=doc["trigger"]["cron"], skill=doc["id"],
                path=f"/tasks/schedules/{doc['id']}/fire",
                timezone=doc["trigger"]["timezone"])
        elif doc["enabled"] and doc["trigger"]["kind"] == "once" \
                and self._dispatcher is not None and self._dispatcher.cloud:
            await self._dispatcher.replace_once(doc["id"], doc["trigger"]["run_at"])
        elif (not doc["enabled"] and doc["trigger"]["kind"] == "once"
              and self._dispatcher is not None and self._dispatcher.cloud):
            await self._dispatcher.delete_once(doc["id"])
        await self._audit("save", doc["id"])
        return doc

    async def get(self, schedule_id: str | None) -> dict | None:
        return await self._db.get(COLLECTION, schedule_id) if schedule_id else None

    async def list(self) -> list[dict]:
        rows = await self._db.query(COLLECTION)
        rows.sort(key=lambda row: row.get("name", ""))
        return rows

    async def _release_fire_claim(self, schedule_id: str, schedule: dict,
                                  claim: str | None) -> dict:
        if not claim:
            return schedule
        released = await self._db.compare_and_set(
            COLLECTION, schedule_id, {"fire_claim": claim},
            {"fire_claim": None, "fire_claim_until": 0.0})
        return released or schedule

    async def delete(self, schedule_id: str) -> bool:
        doc = await self.get(schedule_id)
        if doc is None:
            return False
        if doc.get("trigger", {}).get("kind") == "cron":
            await self._scheduler.delete(schedule_id)
        elif self._dispatcher is not None and self._dispatcher.cloud:
            await self._dispatcher.delete_once(schedule_id)
        await self._db.delete(COLLECTION, schedule_id)
        await self._audit("delete", schedule_id)
        return True

    async def set_enabled(self, schedule_id: str, enabled: bool) -> dict | None:
        doc = await self.get(schedule_id)
        if doc is None:
            return None
        doc["enabled"] = enabled
        return await self.save(doc, schedule_id=schedule_id, source=doc.get("source", "owner"))

    async def fire(self, schedule_id: str, trigger: str = "schedule") -> dict:
        schedule = await self.get(schedule_id)
        if schedule is None:
            raise ScheduleError("schedule not found")
        if not schedule["enabled"] and trigger != "manual":
            return {"ok": False, "skipped": True, "reason": "schedule disabled"}
        claim = None
        if not schedule["allow_overlap"]:
            active = [run for run in await self._runs.list(schedule_id=schedule_id)
                      if run.get("status") in {"queued", "running"}]
            if active:
                return {"ok": False, "skipped": True, "reason": "run already active",
                        "active_run_id": active[0]["id"]}
            now = time.time()
            old_claim = schedule.get("fire_claim")
            old_until = schedule.get("fire_claim_until", 0.0)
            if old_claim and old_until > now:
                return {"ok": False, "skipped": True, "reason": "schedule is firing"}
            claim = uuid4().hex
            schedule = await self._db.compare_and_set(
                COLLECTION, schedule_id,
                {"fire_claim": old_claim, "fire_claim_until": old_until},
                {"fire_claim": claim, "fire_claim_until": now + 600})
            if schedule is None:
                return {"ok": False, "skipped": True, "reason": "schedule is firing"}
            # The claim closes the list/start race. Check once more in case a run
            # was created immediately before this invocation acquired it.
            active = [run for run in await self._runs.list(schedule_id=schedule_id)
                      if run.get("status") in {"queued", "running"}]
            if active:
                schedule.update({"fire_claim": None, "fire_claim_until": 0.0})
                await self._db.put(COLLECTION, schedule_id, schedule)
                return {"ok": False, "skipped": True, "reason": "run already active",
                        "active_run_id": active[0]["id"]}
        input_spec = schedule["input"]
        if input_spec["mode"] == "direct":
            values = input_spec["values"]
            resolver_run_id = None
        else:
            workflow = await self._workflows.get(schedule["workflow"])
            result = await self._agents.run(
                input_spec["prompt"], profile_name=input_spec.get("resolver_agent", ""),
                context={"workflow": schedule["workflow"],
                         "input_schema": workflow["execution"]["inputs"]},
                output_schema=workflow["execution"]["inputs"], origin="schedule-resolver")
            if not result["ok"]:
                await self._release_fire_claim(schedule_id, schedule, claim)
                return {"ok": False, "error": result["error"],
                        "resolver_run_id": result["id"]}
            values, resolver_run_id = result["output"], result["id"]
        try:
            run = await self._runs.start(schedule["workflow"], values, trigger=trigger,
                                         schedule_id=schedule_id)
            run = await self._runs.dispatch(run["id"])
        except Exception:
            await self._release_fire_claim(schedule_id, schedule, claim)
            raise
        schedule["last_run_at"] = time.time()
        schedule["fire_claim"] = None
        schedule["fire_claim_until"] = 0.0
        if schedule["trigger"]["kind"] == "once" and trigger != "manual":
            schedule["enabled"] = False
            schedule["next_run_at"] = None
        elif schedule["trigger"]["kind"] == "cron" and trigger != "manual":
            schedule["next_run_at"] = croniter(
                schedule["trigger"]["cron"],
                datetime.now(ZoneInfo(schedule["trigger"]["timezone"]))).get_next(
                    datetime).timestamp()
        await self._db.put(COLLECTION, schedule_id, schedule)
        return {"ok": run["status"] in {"queued", "running", "succeeded"}, "run": run,
                "resolver_run_id": resolver_run_id}

    async def fire_due(self, now: float | None = None) -> list[dict]:
        timestamp = time.time() if now is None else now
        results = []
        for schedule in await self.list():
            if schedule.get("enabled") and (schedule.get("next_run_at") or float("inf")) <= timestamp:
                results.append(await self.fire(schedule["id"]))
        return results

    async def _audit(self, action: str, schedule_id: str) -> None:
        await self._db.put("audit", f"schedule-{uuid4().hex}", {
            "action": f"workflow_schedule_{action}", "schedule_id": schedule_id,
            "at": time.time()})

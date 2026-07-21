import copy
import json
import time
from uuid import uuid4

from jsonschema import Draft202012Validator

from switchgear.references import ReferenceError

RUNS = "workflow-runs"


class WorkflowRunError(Exception):
    pass


class WorkflowRunBusy(WorkflowRunError):
    pass


def _validate(schema: dict, value, label: str) -> None:
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        detail = "; ".join(error.message for error in errors[:5])
        raise WorkflowRunError(f"{label}: {detail}")


def _cel(expression: str, state: dict):
    from cel_expr_python import cel

    env = cel.NewEnv(variables={name: cel.Type.DYN for name in state})
    return env.compile(expression).eval(data=state).value()


class WorkflowRunner:
    def __init__(self, workflow_store, storage, registry, agent_runner, references,
                 dispatcher=None):
        self._workflows = workflow_store
        self._db = storage
        self._registry = registry
        self._agents = agent_runner
        self._references = references
        self._dispatcher = dispatcher

    async def _resolve_value(self, value, snapshot: dict):
        if isinstance(value, str) and value.startswith("@") and " " not in value:
            try:
                resolved = await self._references.resolve(value)
            except ReferenceError:
                pass
            else:
                snapshot[value] = resolved
                return resolved
        if isinstance(value, str):
            resolved, found = await self._references.interpolate(value)
            snapshot.update(found)
            return resolved
        if isinstance(value, list):
            return [await self._resolve_value(item, snapshot) for item in value]
        if isinstance(value, dict):
            return {key: await self._resolve_value(item, snapshot)
                    for key, item in value.items()}
        return value

    async def start(self, workflow_name: str, inputs: dict, *, trigger: str = "manual",
                    schedule_id: str | None = None) -> dict:
        workflow = await self._workflows.get(workflow_name)
        if workflow is None or workflow.get("status") != "active":
            raise WorkflowRunError("workflow not active")
        execution = workflow.get("execution")
        if not execution:
            raise WorkflowRunError("workflow is not executable")
        snapshot: dict = {}
        try:
            resolved = await self._resolve_value(inputs, snapshot)
            execution_snapshot = copy.deepcopy(execution)
            for step in execution_snapshot["steps"]:
                if step["type"] == "agent":
                    step["prompt"], found = await self._references.interpolate(
                        step["prompt"])
                    snapshot.update(found)
                elif step["type"] == "tool" and isinstance(step.get("args"), dict):
                    step["args"] = await self._resolve_value(step["args"], snapshot)
        except ReferenceError as exc:
            raise WorkflowRunError(str(exc)) from None
        _validate(execution["inputs"], resolved, "inputs")
        run_id = f"wfr-{uuid4().hex}"
        now = time.time()
        run = {"id": run_id, "workflow": workflow_name, "trigger": trigger,
               "schedule_id": schedule_id, "status": "queued", "inputs": resolved,
               "reference_snapshot": snapshot, "execution": execution_snapshot,
               "steps": {}, "step_index": 0,
               "output": None, "error": None, "claim_token": None,
               "claim_until": 0.0, "created_at": now, "updated_at": now}
        await self._db.put(RUNS, run_id, run)
        return run

    async def get(self, run_id: str) -> dict | None:
        return await self._db.get(RUNS, run_id)

    async def list(self, workflow: str | None = None,
                   schedule_id: str | None = None) -> list[dict]:
        where = {"workflow": workflow} if workflow else (
            {"schedule_id": schedule_id} if schedule_id else None)
        rows = await self._db.query(RUNS, where=where)
        rows.sort(key=lambda row: row.get("created_at", 0), reverse=True)
        return rows

    async def advance(self, run_id: str,
                      expected_step_index: int | None = None) -> dict:
        run = await self.get(run_id)
        if run is None:
            raise WorkflowRunError("run not found")
        if run["status"] in {"succeeded", "failed", "needs_review"}:
            return run
        if (expected_step_index is not None
                and run["step_index"] != expected_step_index):
            return run
        now = time.time()
        old_token = run.get("claim_token")
        old_until = run.get("claim_until", 0.0)
        if old_token and old_until > now:
            raise WorkflowRunBusy("workflow step is already claimed")
        token = uuid4().hex
        claimed = await self._db.compare_and_set(
            RUNS, run_id,
            {"step_index": run["step_index"], "claim_token": old_token,
             "claim_until": old_until},
            {"claim_token": token, "claim_until": now + 600,
             "status": "running", "updated_at": now})
        if claimed is None:
            raise WorkflowRunBusy("workflow step claim was lost")
        run = claimed
        execution = run.get("execution")
        if execution is None:  # compatibility for runs created before snapshots
            workflow = await self._workflows.get(run["workflow"])
            execution = workflow["execution"]
        steps = execution["steps"]
        index = run["step_index"]
        state = {"inputs": run["inputs"], "steps": run["steps"],
                 "refs": run["reference_snapshot"],
                 "run": {"id": run_id, "workflow": run["workflow"]}}
        started = time.time()
        try:
            if index >= len(steps):
                values = list(run["steps"].values())
                output = (_cel(execution["output"], state)
                          if execution.get("output")
                          else (values[-1].get("output") if values else None))
                _validate(execution["outputs"], output, "workflow output")
                run.update({"status": "succeeded", "output": output,
                            "claim_token": None, "claim_until": 0.0,
                            "updated_at": time.time()})
                await self._db.put(RUNS, run_id, run)
                return run
            step = steps[index]
            if step.get("when") and not bool(_cel(step["when"], state)):
                output, status = None, "skipped"
            elif step["type"] == "transform":
                output, status = _cel(step["expression"], state), "succeeded"
            elif step["type"] == "tool":
                args = _cel(step["args"], state) if isinstance(step["args"], str) \
                    else step["args"]
                raw = await self._registry.execute(step["tool"], args)
                try:
                    output = json.loads(raw)
                except json.JSONDecodeError:
                    output = raw
                if isinstance(output, dict) and output.get("error"):
                    raise WorkflowRunError(str(output["error"]))
                status = "succeeded"
            else:
                context = _cel(step["context"], state) if step.get("context") else state
                result = await self._agents.run(
                    step["prompt"], profile_name=step.get("agent", ""),
                    skills=step.get("skills"), context=context,
                    output_schema=step.get("output_schema"), origin="workflow")
                if not result["ok"]:
                    raise WorkflowRunError(result["error"] or "agent step failed")
                output, status = result["output"], "succeeded"
            if status != "skipped" and step.get("output_schema"):
                _validate(step["output_schema"], output, f"step {step['id']}")
            run["steps"][step["id"]] = {"status": status, "output": output,
                                             "started_at": started,
                                             "finished_at": time.time()}
            run["step_index"] += 1
            run["claim_token"] = None
            run["claim_until"] = 0.0
            run["updated_at"] = time.time()
        except Exception as exc:
            run.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                        "claim_token": None, "claim_until": 0.0,
                        "updated_at": time.time()})
        await self._db.put(RUNS, run_id, run)
        return run

    async def run_to_completion(self, run_id: str) -> dict:
        run = await self.get(run_id)
        while run and run["status"] not in {"succeeded", "failed", "needs_review"}:
            run = await self.advance(run_id)
        return run

    async def dispatch(self, run_id: str) -> dict:
        run = await self.get(run_id)
        if self._dispatcher is not None and self._dispatcher.cloud:
            await self._dispatcher.enqueue_run(run_id, run["step_index"])
            return run
        return await self.run_to_completion(run_id)

    async def advance_and_dispatch(self, run_id: str,
                                   expected_step_index: int | None = None) -> dict:
        run = await self.advance(run_id, expected_step_index)
        if (self._dispatcher is not None and self._dispatcher.cloud
                and run["status"] not in {"succeeded", "failed", "needs_review"}):
            await self._dispatcher.enqueue_run(run_id, run["step_index"])
        return run

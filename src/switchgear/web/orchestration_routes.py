from fastapi import Body, Depends
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from switchgear import auth
from switchgear.agents.model import AgentProfileError
from switchgear.references import ReferenceError
from switchgear.web.cron import require_cron
from switchgear.workflow_schedules import ScheduleError
from switchgear.workflows.runner import WorkflowRunBusy, WorkflowRunError


class AgentProfilePut(BaseModel):
    text: str


class AgentTestRequest(BaseModel):
    prompt: str
    context: object | None = None


class WorkflowRunRequest(BaseModel):
    inputs: dict = Field(default_factory=dict)


class WorkflowDefinitionPut(BaseModel):
    text: str


class ResolveReferences(BaseModel):
    references: list[str]


class AssistRequest(BaseModel):
    prompt: str
    draft: str = ""
    workflow: str = ""


def register_orchestration_routes(app, state) -> None:
    @app.get("/api/assist")
    async def list_assist_presets(email: str = Depends(auth.require_owner)):
        return state.assists.list()

    @app.post("/api/assist/{preset_id}")
    async def run_assist(preset_id: str, body: AssistRequest,
                         email: str = Depends(auth.require_owner)):
        result = await state.assists.run(preset_id, body.prompt, draft=body.draft,
                                         workflow=body.workflow)
        if not result.get("ok") and result.get("error", "").startswith("unknown"):
            raise StarletteHTTPException(404, result["error"])
        return result

    @app.get("/api/agents")
    async def list_agents(email: str = Depends(auth.require_owner)):
        return await state.agent_profiles.list()

    @app.get("/api/agents/{name}")
    async def get_agent(name: str, email: str = Depends(auth.require_owner)):
        doc = await state.agent_profiles.get(name)
        if doc is None:
            raise StarletteHTTPException(404, "agent profile not found")
        return doc

    @app.put("/api/agents/{name}")
    async def put_agent(name: str, body: AgentProfilePut,
                        email: str = Depends(auth.require_owner)):
        try:
            parsed = state.agent_profiles.validate(body.text)
            if parsed["name"] != name:
                raise AgentProfileError("profile name does not match URL")
            doc = await state.agent_profiles.save(body.text, source="owner")
        except AgentProfileError as exc:
            raise StarletteHTTPException(400, str(exc)) from None
        return doc

    @app.delete("/api/agents/{name}")
    async def delete_agent(name: str, email: str = Depends(auth.require_owner)):
        if not await state.agent_profiles.delete(name):
            raise StarletteHTTPException(404, "agent profile not found")
        return {"ok": True}

    @app.post("/api/agents/{name}/test")
    async def test_agent(name: str, body: AgentTestRequest,
                         email: str = Depends(auth.require_owner)):
        return await state.agent_runner.run(body.prompt, profile_name=name,
                                            context=body.context, origin="profile-test")

    @app.get("/api/schedules")
    async def list_schedules(email: str = Depends(auth.require_owner)):
        return await state.workflow_schedules.list()

    @app.post("/api/schedules")
    async def create_schedule(body: dict = Body(...),
                              email: str = Depends(auth.require_owner)):
        try:
            return await state.workflow_schedules.save(body)
        except ScheduleError as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.get("/api/schedules/{schedule_id}")
    async def get_schedule(schedule_id: str, email: str = Depends(auth.require_owner)):
        doc = await state.workflow_schedules.get(schedule_id)
        if doc is None:
            raise StarletteHTTPException(404, "schedule not found")
        return doc

    @app.put("/api/schedules/{schedule_id}")
    async def update_schedule(schedule_id: str, body: dict = Body(...),
                              email: str = Depends(auth.require_owner)):
        if await state.workflow_schedules.get(schedule_id) is None:
            raise StarletteHTTPException(404, "schedule not found")
        try:
            return await state.workflow_schedules.save(body, schedule_id=schedule_id)
        except ScheduleError as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.delete("/api/schedules/{schedule_id}")
    async def delete_schedule(schedule_id: str,
                              email: str = Depends(auth.require_owner)):
        if not await state.workflow_schedules.delete(schedule_id):
            raise StarletteHTTPException(404, "schedule not found")
        return {"ok": True}

    @app.post("/api/schedules/{schedule_id}/run")
    async def run_schedule(schedule_id: str, email: str = Depends(auth.require_owner)):
        try:
            return await state.workflow_schedules.fire(schedule_id, trigger="manual")
        except (ScheduleError, WorkflowRunError) as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.post("/api/schedules/{schedule_id}/{verb}")
    async def schedule_state(schedule_id: str, verb: str,
                             email: str = Depends(auth.require_owner)):
        if verb not in {"enable", "disable"}:
            raise StarletteHTTPException(404, "unknown schedule operation")
        doc = await state.workflow_schedules.set_enabled(schedule_id, verb == "enable")
        if doc is None:
            raise StarletteHTTPException(404, "schedule not found")
        return doc

    @app.get("/api/schedules/{schedule_id}/runs")
    async def schedule_runs(schedule_id: str, email: str = Depends(auth.require_owner)):
        return await state.workflow_runner.list(schedule_id=schedule_id)

    @app.post("/tasks/schedules/{schedule_id}/fire")
    async def fire_schedule_task(schedule_id: str, _: str = Depends(require_cron)):
        try:
            return await state.workflow_schedules.fire(schedule_id)
        except (ScheduleError, WorkflowRunError) as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.post("/tasks/workflow-runs/{run_id}/advance")
    async def advance_workflow_task(run_id: str, step: int | None = None,
                                    _: str = Depends(require_cron)):
        try:
            return await state.workflow_runner.advance_and_dispatch(run_id, step)
        except WorkflowRunBusy as exc:
            raise StarletteHTTPException(503, str(exc)) from None
        except WorkflowRunError as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.get("/api/workflows/{name}/runs")
    async def workflow_runs(name: str, email: str = Depends(auth.require_owner)):
        return await state.workflow_runner.list(workflow=name)

    @app.put("/api/workflows/{name}/definition")
    async def put_workflow_definition(name: str, body: WorkflowDefinitionPut,
                                      email: str = Depends(auth.require_owner)):
        try:
            parsed = state.workflow_store.validate(body.text)
            if parsed["name"] != name:
                raise WorkflowRunError("workflow name does not match URL")
            return await state.workflow_store.save(body.text, source="owner")
        except Exception as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.post("/api/workflows/{name}/runs")
    async def start_workflow(name: str, body: WorkflowRunRequest,
                             email: str = Depends(auth.require_owner)):
        try:
            run = await state.workflow_runner.start(name, body.inputs)
            return await state.workflow_runner.dispatch(run["id"])
        except WorkflowRunError as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.get("/api/workflows/{name}/runs/{run_id}")
    async def get_workflow_run(name: str, run_id: str,
                               email: str = Depends(auth.require_owner)):
        run = await state.workflow_runner.get(run_id)
        if run is None or run["workflow"] != name:
            raise StarletteHTTPException(404, "workflow run not found")
        return run

    @app.get("/api/references/suggest")
    async def suggest_references(parent: str = "", q: str = "",
                                 email: str = Depends(auth.require_owner)):
        try:
            return await state.references.suggest(parent, q)
        except ReferenceError as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.post("/api/references/resolve")
    async def resolve_references(body: ResolveReferences,
                                 email: str = Depends(auth.require_owner)):
        try:
            return {ref: await state.references.resolve(ref) for ref in body.references}
        except ReferenceError as exc:
            raise StarletteHTTPException(400, str(exc)) from None

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from switchgear import auth
from switchgear.chat_runs import ChatRun
from switchgear.artifacts import resolve_artifact_path
from switchgear.browser import BrowserManager
from switchgear.config import DEV_SESSION_SECRET, Settings, get_settings
from switchgear.conversations import ConversationStore
from switchgear.email import get_email_sender
from switchgear.gateway import Gateway
from switchgear.loop import AgentLoop
from switchgear.live import LiveUpdates, NotifyingStorage
from switchgear.memory.embeddings import get_embedder
from switchgear.memory.store import MemoryStore
from switchgear.pdf import get_pdf_renderer, resume_artifact_dir
from switchgear.prompts import system_prompt
from switchgear.resume.pipeline import TailorPipeline
from switchgear.storage import get_storage
from switchgear.tools import build_registry
from switchgear.web.cron import require_cron
from switchgear.web.deps import AppState
from switchgear.web.spa import spa_index, spa_response

WEB_DIR = Path(__file__).parent

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    conversation_id: str
    message: str


class SkillPutRequest(BaseModel):
    text: str


def create_app(settings: Settings | None = None, gateway=None, storage=None,
               email_sender=None, *, validate_settings: bool = False) -> FastAPI:
    settings = settings or get_settings()
    if validate_settings:
        settings.validate_runtime()
    if settings.session_secret == DEV_SESSION_SECRET and settings.storage_backend == "firestore":
        raise RuntimeError("SWITCHGEAR_SESSION_SECRET must be set in production")
    state_dir = Path(settings.state_dir)
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        probe = state_dir / ".switchgear-write-check"
        probe.touch(exist_ok=True)
        probe.unlink()
    except OSError as exc:
        raise RuntimeError(f"state directory is not writable: {state_dir}: {exc}") from exc
    live_updates = LiveUpdates()
    storage = NotifyingStorage(storage or get_storage(settings), live_updates)
    gateway = gateway or Gateway(settings)
    email_sender = email_sender or get_email_sender(settings)
    from switchgear.channels.sendfns import SendFunctionStore
    from switchgear.resources.store import ResourceStore, make_bank_provider
    from switchgear.scheduler import CloudScheduler, LocalScheduler
    from switchgear.skills.runner import SkillRunner
    from switchgear.skills.store import SkillStore
    from switchgear.skills.model import SkillParseError
    from switchgear.agents.store import AgentProfileStore

    skill_store = SkillStore(storage)
    agent_profiles = AgentProfileStore(storage)
    from switchgear.skills.agent_writes import SkillWriteService

    skill_writes = SkillWriteService(skill_store, storage)
    scheduler = (CloudScheduler(storage, settings)
                 if settings.scheduler_backend == "cloud"
                 else LocalScheduler(storage, settings))
    resource_store = ResourceStore(storage, settings)
    from switchgear.resources.agent_writes import AgentWriteService

    resource_writes = AgentWriteService(resource_store, storage)
    sendfn_store = SendFunctionStore(storage, settings)
    bank_provider = make_bank_provider(resource_store, settings)
    tailor_pipeline = TailorPipeline(gateway, storage, bank_provider,
                                     get_pdf_renderer(settings), settings)
    browser_manager = BrowserManager(settings)
    embedder = get_embedder(settings)
    memory_store = MemoryStore(storage, embedder, settings)
    from switchgear.memory.reflection import ReflectionPass

    reflection = ReflectionPass(gateway, memory_store, storage, settings)
    registry = build_registry(settings, storage, gateway, email_sender,
                              skill_store, scheduler,
                              tailor_pipeline=tailor_pipeline,
                              browser_manager=browser_manager,
                              resource_store=resource_store,
                              resource_writes=resource_writes,
                              skill_writes=skill_writes,
                              memory_store=memory_store)
    from switchgear.workflows.actions import GatedActionService
    from switchgear.workflows.plugins.apply import SubmitApplicationExecutor
    from switchgear.workflows.plugins.brief import LlmBriefGenerator
    from switchgear.workflows.plugins.channel_send import ChannelSendExecutor
    from switchgear.workflows.plugins.digest import SendDigestExecutor
    from switchgear.workflows.plugins.tailor import TailorResumeGenerator
    from switchgear.workflows.registry import WorkflowPlugins
    from switchgear.workflows.store import WorkflowStore
    from switchgear.channels.model import ChannelStore, poll_cron, validate_channel_refs
    from switchgear.channels.send import ChannelSendService
    from switchgear.tools.channel_tools import make_channel_messages_tool, make_channel_send_tool

    workflow_plugins = WorkflowPlugins()
    workflow_plugins.register_generator(
        "tailor-resume", TailorResumeGenerator(tailor_pipeline))
    workflow_plugins.register_executor(
        "submit-application",
        SubmitApplicationExecutor(storage, browser_manager, registry, settings))
    workflow_plugins.register_generator("llm-brief",
                                        LlmBriefGenerator(gateway, storage))
    workflow_plugins.register_executor(
        "send-digest",
        SendDigestExecutor(storage, email_sender, settings,
                           artifacts_collection="wf-research-artifacts",
                           item_ref_field="item_key"))
    # Registered BEFORE WorkflowStore so the seeded channel-email WORKFLOW.md
    # (actions.executor: channel-send) parses; the service is bound during
    # channel activation in lifespan (Task 5 completes that wiring).
    channel_send_executor = ChannelSendExecutor(None)
    workflow_plugins.register_executor("channel-send", channel_send_executor)
    workflow_store = WorkflowStore(storage,
                                   generators=workflow_plugins.generator_names,
                                   executors=workflow_plugins.executor_names)
    from switchgear.agents.runner import AgentRunner
    from switchgear.references import ReferenceService
    from switchgear.workflows.runner import WorkflowRunner
    from switchgear.workflow_schedules import WorkflowScheduleService
    from switchgear.task_dispatcher import CloudTaskDispatcher, TaskDispatcher

    references = ReferenceService(resource_store, workflow_store)
    agent_runner = AgentRunner(gateway, registry, agent_profiles, skill_store,
                               storage, settings)
    dispatcher = (CloudTaskDispatcher(settings) if settings.scheduler_backend == "cloud"
                  else TaskDispatcher())
    workflow_runner = WorkflowRunner(workflow_store, storage, registry,
                                     agent_runner, references, dispatcher)
    workflow_schedules = WorkflowScheduleService(
        storage, scheduler, workflow_store, workflow_runner, agent_runner, dispatcher)
    channel_store = ChannelStore(storage)
    from switchgear.definition_writes import DefinitionWriteService

    definition_writes = DefinitionWriteService(
        storage, {"agent": agent_profiles, "workflow": workflow_store,
                  "channel": channel_store})
    from switchgear.assist import AssistService

    assists = AssistService(agent_runner, workflow_store)
    from switchgear.tools.workflow_schedule_tool import make_workflow_schedule_tool

    registry.register(make_workflow_schedule_tool(workflow_schedules))
    from switchgear.tools.definition_tools import (
        make_agents_tool,
        make_channels_tool,
        make_workflows_tool,
    )

    registry.register(make_agents_tool(agent_profiles, definition_writes))
    registry.register(make_workflows_tool(workflow_store, workflow_runner,
                                          definition_writes))
    registry.register(make_channels_tool(channel_store, definition_writes))

    from switchgear.tools.workflow_items import make_workflow_items_tool

    registry.register(make_workflow_items_tool(workflow_store, storage))
    registry.register(make_channel_messages_tool(workflow_store, storage))
    gated_actions = GatedActionService(storage, workflow_plugins, settings)
    from switchgear.approvals import ApprovalRouter

    approvals = ApprovalRouter(resource_writes, skill_writes,
                               workflow_store, gated_actions, definition_writes,
                               settings.approval_chat_escalation_seconds)
    state = AppState(
        settings=settings, gateway=gateway, storage=storage, registry=registry,
        conversations=ConversationStore(storage), skill_store=skill_store,
        skill_writes=skill_writes,
        scheduler=scheduler,
        skill_runner=SkillRunner(gateway, registry, skill_store, settings,
                                 storage, email_sender, memory_store=memory_store),
        agent_profiles=agent_profiles, agent_runner=agent_runner,
        resource_store=resource_store, resource_writes=resource_writes,
        bank_provider=bank_provider,
        tailor_pipeline=tailor_pipeline,
        browser_manager=browser_manager,
        workflow_store=workflow_store, workflow_plugins=workflow_plugins,
        workflow_runner=workflow_runner, workflow_schedules=workflow_schedules,
        references=references,
        assists=assists,
        definition_writes=definition_writes,
        gated_actions=gated_actions,
        channel_store=channel_store,
        embedder=embedder, memory_store=memory_store,
        reflection=reflection,
        sendfn_store=sendfn_store,
        live_updates=live_updates)
    state.approvals = approvals

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from switchgear.web.settings_routes import (
            load_secure_overrides,
            load_settings_overrides,
        )
        from switchgear.web.setup_routes import announce_setup, ensure_session_secret

        await load_settings_overrides(state)
        await load_secure_overrides(state)
        await ensure_session_secret(state)
        await announce_setup(state)
        await state.skill_store.seed_dir(settings.skills_dir)
        await state.agent_profiles.seed_dir(settings.agents_dir)
        await state.workflow_store.seed_dir(settings.workflows_dir)
        # One-release compatibility migration: old skill cron metadata/jobs become
        # workflow schedules when exactly one workflow names that skill as intake.
        legacy_jobs = {row["skill"]: row for row in await state.scheduler.list()
                       if not row["skill"].startswith("sch-")}
        for skill in await state.skill_store.list():
            cron = (legacy_jobs.get(skill["name"]) or {}).get("cron") or skill.get("schedule")
            if not cron or skill["status"] != "active":
                continue
            matches = [wf for wf in await state.workflow_store.active_definitions()
                       if skill["name"] in (wf.get("intake") or {}).get("skills", [])
                       and wf.get("execution")]
            existing = [row for row in await state.workflow_schedules.list()
                        if row["workflow"] in {wf["name"] for wf in matches}]
            if len(matches) == 1 and not existing:
                await state.workflow_schedules.save({
                    "name": f"{matches[0]['name']} schedule",
                    "workflow": matches[0]["name"], "enabled": True,
                    "trigger": {"kind": "cron", "cron": cron,
                                "timezone": settings.owner_timezone},
                    "input": {"mode": "direct", "values": {}},
                    "allow_overlap": False,
                }, source="migration")
                if skill["name"] in legacy_jobs:
                    await state.scheduler.delete(skill["name"])
        for workflow in await state.workflow_store.active_definitions():
            await state.workflow_store.purge_expired_items(workflow)
        await state.resource_store.seed_dir(settings.resources_dir)

        from switchgear.channels.ingest import ChannelIngest
        from switchgear.channels.transport import get_transport
        from switchgear.channels.triage import ChannelTriage

        schedule_tick_task = None
        if settings.scheduler_backend == "local":
            async def _schedule_tick():
                while True:
                    try:
                        await state.workflow_schedules.fire_due()
                    except Exception:
                        logger.exception("local schedule tick failed")
                    await asyncio.sleep(15)

            schedule_tick_task = asyncio.create_task(_schedule_tick())

        await state.channel_store.seed_dir(settings.channels_dir)
        scheduled_docs = await state.scheduler.list()
        scheduled = {s["skill"] for s in scheduled_docs}
        scheduled_by_skill = {s["skill"]: s for s in scheduled_docs}
        for row in await state.channel_store.list():
            if row["status"] != "active":
                continue
            channel = await state.channel_store.get(row["name"])
            fns = {f["name"]: f for f in await state.sendfn_store.list()}
            problems = await validate_channel_refs(
                channel, workflow_store=state.workflow_store,
                send_function_names=set(fns), send_functions=fns)
            if problems:
                logger.warning("channel %s not activated: %s",
                               channel["name"], "; ".join(problems))
                continue
            transport = get_transport(settings)
            service = ChannelSendService(
                storage, transport, state.sendfn_store, state.workflow_store,
                state.gated_actions, channel, settings)
            state.channel_send[channel["name"]] = service
            triage = ChannelTriage(gateway, channel, state.workflow_store,
                                   service, storage, settings)
            state.channel_triage[channel["name"]] = triage
            state.channels[channel["name"]] = ChannelIngest(
                channel, transport, state.workflow_store,
                storage, settings, triage=triage)
            # v1 runs exactly one channel; the executor binds to the last
            # active one. Multi-channel needs per-workflow executor wiring
            # (out of scope, spec §10).
            channel_send_executor.send_service = service
            state.registry.register(make_channel_send_tool(service))
            job = f"poll-{channel['name']}"
            if job not in scheduled:
                await state.scheduler.create(
                    name=job, cron=poll_cron(channel["poll_interval"]), skill=job,
                    path=f"/tasks/poll-channel/{channel['name']}")
            else:
                existing = scheduled_by_skill.get(job, {})
                expected = f"/tasks/poll-channel/{channel['name']}"
                if expected not in existing.get("target_url", ""):
                    logger.warning(
                        "channel poll job name shadowed by existing schedule %r",
                        job)
        try:
            yield
        finally:
            if schedule_tick_task is not None:
                schedule_tick_task.cancel()
                try:
                    await schedule_tick_task
                except asyncio.CancelledError:
                    pass
            await state.chat_runs.shutdown()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.switchgear = state
    app.include_router(auth.router)

    async def _app_settings() -> Settings:
        return settings

    app.dependency_overrides[get_settings] = _app_settings

    @app.middleware("http")
    async def same_origin_csrf(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.cookies.get("session"):
            origin = request.headers.get("origin")
            expected = settings.public_base_url.rstrip("/")
            if origin and origin.rstrip("/") != expected:
                return JSONResponse({"detail": "cross-origin request rejected"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 401 and "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/login", status_code=307)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                            headers=exc.headers)

    static_dir = WEB_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
    jinja = Environment(loader=FileSystemLoader(WEB_DIR / "templates"), autoescape=True)

    async def _workflow_summaries():
        out = []
        for row in await state.workflow_store.list():
            if row["status"] != "active":
                continue
            wf = await state.workflow_store.get(row["name"])
            stale = False
            period = (wf.get("items") or {}).get("expected_update_period")
            if period:
                latest = 0.0
                for skill_name in wf["intake"]["skills"]:
                    for run in await state.storage.query("runs",
                                                         where={"skill": skill_name}):
                        if run.get("ok") and (run.get("at") or 0) > latest:
                            latest = run["at"]
                stale = (time.time() - latest) > period
            out.append({"name": wf["name"], "description": wf["description"],
                        "ui_home": wf.get("ui_home", "workflows"),
                        "status": row["status"], "stale": stale})
        return out

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/version")
    async def version():
        return {"version": os.getenv("SWITCHGEAR_VERSION", "development")}

    @app.get("/", response_class=HTMLResponse)
    async def index(email: str = Depends(auth.require_owner)):
        if spa_index():
            return spa_response()
        return jinja.get_template("chat.html").render(
            owner=email, active="chat", workflows=await _workflow_summaries())

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if not state.settings.local_password_hash:
            return RedirectResponse("/setup", status_code=307)
        if auth.verify_session(settings, request.cookies.get("session")):
            return RedirectResponse("/", status_code=307)
        csrf = auth.login_csrf(settings)
        response = HTMLResponse(jinja.get_template("landing.html").render(
            csrf=csrf))
        response.set_cookie("login_csrf", csrf, httponly=True,
                            secure=settings.cookie_secure,
                            samesite=settings.cookie_samesite,
                            max_age=auth.LOGIN_CSRF_MAX_AGE)
        return response

    @app.get("/skills", response_class=HTMLResponse)
    async def skills_page(email: str = Depends(auth.require_owner)):
        if spa_index():
            return spa_response()
        return jinja.get_template("skills.html").render(
            owner=email, active="skills", workflows=await _workflow_summaries())

    @app.get("/api/conversations")
    async def conversations(email: str = Depends(auth.require_owner)):
        return await state.conversations.list()

    @app.get("/api/conversations/{conv_id}")
    async def conversation_messages(conv_id: str,
                                    email: str = Depends(auth.require_owner)):
        return await state.conversations.load_ui(conv_id)

    @app.get("/api/events")
    async def live_events(email: str = Depends(auth.require_owner)):
        async def events():
            async with state.live_updates.subscribe() as queue:
                yield f"data: {json.dumps({'topic': 'connected'})}\n\n"
                while True:
                    try:
                        topic = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                    else:
                        yield f"data: {json.dumps({'topic': topic})}\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def _reflect_safely(cid: str) -> None:
        try:
            await state.reflection.maybe_reflect(cid)
        except Exception:
            logger.exception("reflection pass failed")

    @app.post("/api/chat")
    async def chat(body: ChatRequest, email: str = Depends(auth.require_owner)):
        conv_id, user_msg = body.conversation_id, body.message

        async def worker(run: ChatRun):
            live_items: list[dict] = []
            try:
                history = await state.conversations.load(conv_id)
                history.append({"role": "user", "content": user_msg})
                # The run is reserved before this first storage await, so a losing
                # concurrent send cannot persist a turn that will never execute.
                await state.conversations.save(conv_id, history, title=user_msg[:60])
                await state.conversations.save_live(conv_id, [], status="running")
                # Rebuild the system message EVERY turn (spec §5.4): live skills,
                # core memories, and per-message recall.
                active = [s for s in await state.skill_store.list()
                          if s["status"] == "active"]
                core, recalled = "", []
                try:
                    core = await state.memory_store.core_block()
                    recalled = await state.memory_store.recall(user_msg)
                except Exception:
                    core, recalled = "", []
                    logger.warning(
                        "memory injection failed — proceeding without memory sections",
                        exc_info=True)
                fresh = system_prompt(settings.owner_email, skills=active,
                                      core_memories=core, recalled=recalled)
                if history and history[0].get("role") == "system":
                    history[0] = {"role": "system", "content": fresh}
                else:
                    history.insert(0, {"role": "system", "content": fresh})
                loop = AgentLoop(state.gateway, state.registry, settings)
                async for event in loop.run(history):
                    kind = event["type"]
                    if kind == "text":
                        if live_items and live_items[-1].get("kind") == "message" \
                                and live_items[-1].get("role") == "assistant":
                            live_items[-1]["content"] += event["delta"]
                        else:
                            live_items.append({"kind": "message", "role": "assistant",
                                               "content": event["delta"]})
                        await state.conversations.save_live(conv_id, live_items)
                        await run.publish(event)
                    elif kind == "tool_call":
                        live_items.append({"kind": "tool", "call_id": "",
                                           "name": event["name"], "args": event["args"]})
                        await state.conversations.save_live(conv_id, live_items)
                        await run.publish(event)
                    elif kind == "tool_result":
                        for item in reversed(live_items):
                            if item.get("kind") == "tool" and "result" not in item:
                                try:
                                    item["result"] = json.loads(event["result"])
                                except json.JSONDecodeError:
                                    item["result"] = event["result"]
                                break
                        await state.conversations.save_live(conv_id, live_items)
                        await run.publish(event)
                    elif kind == "done":
                        await state.conversations.save(
                            conv_id, event["messages"], title=user_msg[:60],
                            clear_live=True)
                        task = asyncio.create_task(_reflect_safely(conv_id))
                        state.reflection_tasks.add(task)
                        task.add_done_callback(state.reflection_tasks.discard)
                        await run.publish({"type": "done", "usage": event["usage"]})
                    elif kind == "error" and "messages" in event:
                        await state.conversations.save(
                            conv_id, event["messages"], title=user_msg[:60],
                            clear_live=True)
                        frame = {k: v for k, v in event.items() if k != "messages"}
                        await state.conversations.save_live(
                            conv_id, [{"kind": "message", "role": "error",
                                       "content": frame["reason"]}], status="error")
                        await run.publish(frame)
                    else:
                        await run.publish(event)
            except asyncio.CancelledError:
                await state.conversations.save_live(
                    conv_id, live_items + [{"kind": "message", "role": "error",
                                            "content": "run interrupted by server shutdown"}],
                    status="error")
                raise
            except Exception as e:
                reason = f"internal error: {type(e).__name__}"
                live_items.append({"kind": "message", "role": "error", "content": reason})
                await state.conversations.save_live(conv_id, live_items, status="error")
                await run.publish({"type": "error", "reason": reason})
            finally:
                await run.finish()

        try:
            # start() performs no await: reservation is atomic within this event loop.
            run = state.chat_runs.start(conv_id, worker)
        except RuntimeError as exc:
            raise StarletteHTTPException(
                409, "conversation already has an active run") from exc
        return StreamingResponse(
            run.stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/tasks/run-skill/{name}")
    async def run_skill_task(name: str, _: str = Depends(require_cron)):
        return await state.skill_runner.run(name, trigger="schedule")

    @app.get("/api/skills")
    async def list_skills(email: str = Depends(auth.require_owner)):
        return await state.skill_store.list()

    @app.get("/api/skills/{name}")
    async def get_skill(name: str, email: str = Depends(auth.require_owner)):
        doc = await state.skill_store.get(name)
        if doc is None:
            raise StarletteHTTPException(404, "skill not found")
        return doc

    @app.put("/api/skills/{name}")
    async def put_skill(name: str, body: SkillPutRequest,
                        email: str = Depends(auth.require_owner)):
        try:
            parsed = state.skill_store.validate(body.text)
            if parsed["name"] != name:
                raise SkillParseError("skill name does not match URL")
            doc = await state.skill_store.save(body.text, source="owner")
        except SkillParseError as exc:
            raise StarletteHTTPException(400, str(exc)) from None
        return doc

    @app.post("/api/skills/{name}/approve")
    async def approve_skill(name: str, email: str = Depends(auth.require_owner)):
        doc = await state.skill_store.set_status(name, "active")
        if doc is None:
            raise StarletteHTTPException(404, "skill not found")
        await state.storage.put("audit", f"approve-{uuid4().hex}", {
            "action": "skill_approve", "skill": name, "at": time.time()})
        return {"name": name, "status": doc["status"]}

    @app.post("/api/skills/{name}/run")
    async def run_skill_owner(name: str, email: str = Depends(auth.require_owner)):
        return await state.skill_runner.run(name, trigger="manual")

    @app.get("/api/skills/{name}/runs")
    async def skill_runs(name: str, email: str = Depends(auth.require_owner)):
        runs = await state.storage.query("runs", where={"skill": name})
        runs.sort(key=lambda r: r.get("at", 0), reverse=True)
        return runs

    @app.get("/resumes/{filename}")
    async def resume_file(filename: str, email: str = Depends(auth.require_owner)):
        try:
            path = resolve_artifact_path(resume_artifact_dir(settings), filename)
        except ValueError:
            raise StarletteHTTPException(400, "invalid filename")
        if not path.is_file():
            raise StarletteHTTPException(404, "resume artifact not found")
        return FileResponse(path)

    @app.get("/screenshots/{filename}")
    async def screenshot_file(filename: str, email: str = Depends(auth.require_owner)):
        try:
            path = resolve_artifact_path(state.browser_manager.screenshot_dir, filename)
        except ValueError:
            raise StarletteHTTPException(400, "invalid filename")
        if not path.is_file():
            raise StarletteHTTPException(404, "screenshot not found")
        return FileResponse(path)

    from switchgear.web.workflow_routes import register_workflow_routes

    from switchgear.web.orchestration_routes import register_orchestration_routes

    register_orchestration_routes(app, state)

    register_workflow_routes(app, state, jinja, _workflow_summaries)

    from switchgear.web.storage_routes import register_storage_routes

    register_storage_routes(app, state, jinja, _workflow_summaries)

    from switchgear.web.channel_routes import register_channel_routes

    register_channel_routes(app, state, jinja, _workflow_summaries)

    from switchgear.web.approval_routes import register_approval_routes

    register_approval_routes(app, state)

    from switchgear.web.settings_routes import register_settings_routes

    register_settings_routes(app, state)

    from switchgear.web.setup_routes import register_setup_routes

    register_setup_routes(app, state)

    return app

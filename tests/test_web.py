import asyncio
import json

import httpx
import pytest

from switchgear.channels.ingest import message_key
from switchgear.config import Settings
from switchgear.auth import sign_session
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from tests.fakes import FakeGateway

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")


def make_client(gateway):
    app = create_app(settings=S, gateway=gateway, storage=MemoryStorage())
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    return c


async def test_healthz_no_auth():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        assert (await c.get("/healthz")).json() == {"ok": True}


async def test_chat_requires_auth():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        r = await c.post("/api/chat", json={"conversation_id": "c1", "message": "hi"})
    assert r.status_code == 401


async def test_chat_streams_and_persists():
    gw = FakeGateway([[{"type": "text", "delta": "hello"},
                       {"type": "message", "usage": 3,
                        "message": {"role": "assistant", "content": "hello"}}]])
    async with make_client(gw) as c:
        r = await c.post("/api/chat", json={"conversation_id": "c1", "message": "hi"})
        events = [json.loads(line[6:]) for line in r.text.splitlines()
                  if line.startswith("data: ")]
    assert events[0] == {"type": "text", "delta": "hello"}
    assert events[-1]["type"] == "done"
    # system prompt was prepended
    assert gw.calls[0]["messages"][0]["role"] == "system"


async def test_concurrent_chat_send_is_rejected_before_persisting_losing_turn():
    gw = FakeGateway([[{"type": "message", "usage": 1,
                        "message": {"role": "assistant", "content": "done"}}]])
    app, c = make_app_client(gw)
    original = app.state.switchgear.conversations
    first_load_started = asyncio.Event()
    release_first_load = asyncio.Event()

    class LatchedConversations:
        async def load(self, conversation_id):
            first_load_started.set()
            await release_first_load.wait()
            return await original.load(conversation_id)

        async def save(self, *args, **kwargs):
            return await original.save(*args, **kwargs)

        async def save_live(self, *args, **kwargs):
            return await original.save_live(*args, **kwargs)

    app.state.switchgear.conversations = LatchedConversations()
    async with c:
        first = asyncio.create_task(c.post(
            "/api/chat", json={"conversation_id": "race", "message": "winner"}))
        await first_load_started.wait()

        losing = await c.post(
            "/api/chat", json={"conversation_id": "race", "message": "loser"})
        assert losing.status_code == 409
        assert await original.load("race") == []

        release_first_load.set()
        assert (await first).status_code == 200

    persisted = await original.load("race")
    assert any(message.get("content") == "winner" for message in persisted)
    assert not any(message.get("content") == "loser" for message in persisted)


async def test_conversation_persisted_same_app():
    gw = FakeGateway([[{"type": "message", "usage": 1,
                        "message": {"role": "assistant", "content": "yo"}}]])
    app = create_app(settings=S, gateway=gw, storage=MemoryStorage())
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    async with c:
        await c.post("/api/chat", json={"conversation_id": "c9", "message": "hi"})
        convs = (await c.get("/api/conversations")).json()
    assert convs and convs[0]["_id"] == "c9"


def tool_call_msg(name, args):
    return {"type": "message", "usage": 10, "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": name, "arguments": json.dumps(args)}}]}}


async def test_budget_error_persists_messages_and_strips_them_from_frame():
    s = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3",
                 run_token_budget=1)
    gw = FakeGateway([[tool_call_msg("storage", {"op": "get", "collection": "c", "key": "k"})]])
    app = create_app(settings=s, gateway=gw, storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        c.cookies.set("session", sign_session(s, "me@example.com"))
        r = await c.post("/api/chat", json={"conversation_id": "budget1", "message": "hi"})
        events = [json.loads(line[6:]) for line in r.text.splitlines()
                  if line.startswith("data: ")]
        assert events[-1] == {"type": "error", "reason": "token budget exceeded"}
        persisted = (await c.get("/api/conversations/budget1")).json()
    assert any(m.get("content") for m in persisted if m.get("role") == "user")


class CrashingGateway:
    async def stream(self, tier, messages, tools=None):
        yield {"type": "text", "delta": "hi"}
        raise RuntimeError("boom")
        yield {}  # pragma: no cover - unreachable, keeps this an async generator


async def test_stream_crash_yields_terminal_error_frame():
    async with make_client(CrashingGateway()) as c:
        r = await c.post("/api/chat", json={"conversation_id": "c-crash", "message": "hi"})
        events = [json.loads(line[6:]) for line in r.text.splitlines()
                  if line.startswith("data: ")]
    assert events[-1]["type"] == "error"
    assert "RuntimeError" in events[-1]["reason"]


async def test_malformed_chat_body_returns_422():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        c.cookies.set("session", sign_session(S, "me@example.com"))
        r = await c.post("/api/chat", json={"conversation_id": "c1"})
    assert r.status_code == 422


async def test_create_app_guards_dev_secret_with_firestore_backend():
    s = Settings(_env_file=None, owner_email="me@example.com",
                session_secret="dev-secret-change-me", storage_backend="firestore")
    with pytest.raises(RuntimeError):
        create_app(settings=s, gateway=FakeGateway([]), storage=MemoryStorage())


async def test_create_app_allows_dev_secret_with_dev_backends():
    s = Settings(_env_file=None, owner_email="me@example.com")
    create_app(settings=s, gateway=FakeGateway([]), storage=MemoryStorage())  # should not raise


async def test_create_app_boots_with_missing_career_dir():
    s = Settings(_env_file=None, owner_email="me@example.com",
                career_dir="does-not-exist")
    app = create_app(settings=s, gateway=FakeGateway([]), storage=MemoryStorage())
    state = app.state.switchgear
    assert state.resource_store is not None
    assert state.tailor_pipeline is not None            # built unconditionally now
    assert "resources" in state.registry._tools
    assert "career_bank" not in state.registry._tools
    assert await state.bank_provider() is None          # no resource, no career dir


async def test_boot_seeds_no_career_bank():
    # First boot must never seed user-specific career data.
    s = Settings(_env_file=None, owner_email="me@example.com", career_dir="career")
    app = create_app(settings=s, gateway=FakeGateway([]), storage=MemoryStorage())
    async with app.router.lifespan_context(app):
        state = app.state.switchgear
        assert await state.resource_store.get("career-bank") is None


async def test_root_unauthenticated_browser_redirects_to_login():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        r = await c.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/login"


async def test_login_page_renders_for_unauthenticated_browser():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        r = await c.get("/login")
    assert r.status_code == 200
    assert 'action="/auth/local"' in r.text
    assert "Owner password" in r.text
    assert "login_csrf=" in r.headers["set-cookie"]


async def test_login_redirects_authenticated_owner_to_root():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    async with c:
        r = await c.get("/login", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/"


async def test_login_with_invalid_cookie_still_renders_page():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", "garbage")
    async with c:
        r = await c.get("/login")
    assert r.status_code == 200 and "Owner password" in r.text


async def test_openapi_docs_and_redoc_disabled():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        assert (await c.get("/openapi.json")).status_code == 404
        assert (await c.get("/docs")).status_code == 404
        assert (await c.get("/redoc")).status_code == 404


async def test_guarded_route_still_works_for_owner_with_docs_disabled():
    async with make_client(FakeGateway([])) as c:
        r = await c.get("/api/conversations")
    assert r.status_code == 200


async def test_api_unauthenticated_still_401_json():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        r = await c.get("/api/conversations")
    assert r.status_code == 401
    assert r.json()["detail"]


async def test_chat_system_prompt_includes_active_skills():
    gw = FakeGateway([[{"type": "message", "usage": 1,
                        "message": {"role": "assistant", "content": "hi"}}]])
    from switchgear.storage.memory import MemoryStorage
    app = create_app(settings=S, gateway=gw, storage=MemoryStorage())
    await app.state.switchgear.skill_store.save(
        "---\nname: job-search\ndescription: Find jobs\ntools: [http_fetch]\n"
        "---\nFind jobs.\n", source="repo")
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    async with c:
        await c.post("/api/chat", json={"conversation_id": "sk1", "message": "hi"})
    assert "job-search" in gw.calls[0]["messages"][0]["content"]


class CountingScheduler:
    """Wraps a Scheduler and records create() calls, for idempotency checks."""

    def __init__(self, inner):
        self._inner = inner
        self.create_calls = []

    async def create(self, name, cron, skill, path=None, timezone="Etc/UTC"):
        self.create_calls.append(name)
        return await self._inner.create(name, cron, skill, path=path,
                                        timezone=timezone)

    async def delete(self, name):
        return await self._inner.delete(name)

    async def list(self):
        return await self._inner.list()


async def test_startup_does_not_treat_seeded_skill_as_a_schedule():
    app = create_app(settings=S, gateway=FakeGateway([]), storage=MemoryStorage())
    async with app.router.lifespan_context(app):
        scheduled = await app.state.switchgear.scheduler.list()
    assert not any(s["skill"] == "job-search" for s in scheduled)


async def test_startup_provisioning_is_idempotent_across_reboots():
    from switchgear.storage.memory import MemoryStorage as _MemoryStorage
    storage = _MemoryStorage()

    app1 = create_app(settings=S, gateway=FakeGateway([]), storage=storage)
    async with app1.router.lifespan_context(app1):
        pass

    app2 = create_app(settings=S, gateway=FakeGateway([]), storage=storage)
    counting = CountingScheduler(app2.state.switchgear.scheduler)
    app2.state.switchgear.scheduler = counting
    async with app2.router.lifespan_context(app2):
        scheduled = await app2.state.switchgear.scheduler.list()

    assert counting.create_calls == []
    assert not any(s["skill"] == "job-search" for s in scheduled)


async def test_startup_does_not_provision_pending_skill_schedule():
    from switchgear.storage.memory import MemoryStorage as _MemoryStorage
    storage = _MemoryStorage()
    app = create_app(settings=S, gateway=FakeGateway([]), storage=storage)
    await app.state.switchgear.skill_store.save(
        "---\nname: draft-digest\ndescription: A drafted digest\n"
        "tools: [http_fetch]\nschedule: \"0 8 * * *\"\n---\nDraft.\n", source="agent")

    async with app.router.lifespan_context(app):
        scheduled = await app.state.switchgear.scheduler.list()

    assert not any(s["skill"] == "draft-digest" for s in scheduled)


async def test_startup_does_not_migrate_removed_domain_skill_schedule():
    from switchgear.skills.store import SkillStore
    from switchgear.storage.memory import MemoryStorage as _MemoryStorage

    storage = _MemoryStorage()
    await SkillStore(storage).save(
        "---\nname: job-search\ndescription: Legacy scheduled search\n"
        "tools: [fetch_jobs]\nschedule: \"0 9 * * *\"\n---\nSearch.\n",
        source="repo")
    app = create_app(settings=S, gateway=FakeGateway([]), storage=storage)
    async with app.router.lifespan_context(app):
        schedules = await app.state.switchgear.workflow_schedules.list()

    assert schedules == []


# ---------- per-turn system message rebuild (storage layer phase 3) ----------


def assistant_msg(text, usage=1):
    return [{"type": "message", "usage": usage,
             "message": {"role": "assistant", "content": text}}]


def make_app_client(gw):
    app = create_app(settings=S, gateway=gw, storage=MemoryStorage())
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(S, "me@example.com"))
    return app, c


async def test_chat_without_memories_renders_no_memory_sections():
    gw = FakeGateway([assistant_msg("hi")])
    _app, c = make_app_client(gw)
    async with c:
        await c.post("/api/chat", json={"conversation_id": "nm1", "message": "hi"})
    sysmsg = gw.calls[0]["messages"][0]["content"]
    assert "## Standing instructions (memories)" not in sysmsg
    assert "## Possibly relevant memories" not in sysmsg


async def test_chat_system_message_rebuilt_with_new_core_memory_on_second_turn():
    gw = FakeGateway([assistant_msg("one"), assistant_msg("two")])
    app, c = make_app_client(gw)
    async with c:
        await c.post("/api/chat", json={"conversation_id": "m1", "message": "hi"})
        await app.state.switchgear.memory_store.save(
            text="Always sign off with -D", type="core", importance=8)
        await c.post("/api/chat", json={"conversation_id": "m1", "message": "again"})
    first = gw.calls[0]["messages"][0]["content"]
    second = gw.calls[1]["messages"][0]["content"]
    assert "Always sign off with -D" not in first
    assert "## Standing instructions (memories)" in second
    assert "Always sign off with -D" in second
    # rebuilt in place: still exactly one system message
    assert [m["role"] for m in gw.calls[1]["messages"]].count("system") == 1


async def test_chat_recalled_memories_appear_in_system_message():
    gw = FakeGateway([assistant_msg("ok")])
    app, c = make_app_client(gw)
    # FakeEmbedder is deterministic: an identical query text guarantees cosine 1.0,
    # comfortably above the 0.55 recall floor.
    await app.state.switchgear.memory_store.save(
        text="The dog is named Biscuit", type="episodic", importance=5)
    async with c:
        await c.post("/api/chat", json={"conversation_id": "rc1",
                                        "message": "The dog is named Biscuit"})
    sysmsg = gw.calls[0]["messages"][0]["content"]
    assert "## Possibly relevant memories" in sysmsg
    assert "The dog is named Biscuit" in sysmsg
    assert "(saved " in sysmsg


async def test_chat_system_message_picks_up_skill_activated_between_turns():
    # Regression for the pre-existing staleness bug fixed by the per-turn rebuild
    # (spec §5.4): a conversation started before a skill activation must see it.
    gw = FakeGateway([assistant_msg("one"), assistant_msg("two")])
    app, c = make_app_client(gw)
    async with c:
        await c.post("/api/chat", json={"conversation_id": "sk2", "message": "hi"})
        await app.state.switchgear.skill_store.save(
            "---\nname: mid-conv\ndescription: Added mid-conversation\n"
            "tools: [http_fetch]\n---\nBody.\n", source="repo")  # repo => active
        await c.post("/api/chat", json={"conversation_id": "sk2", "message": "again"})
    assert "mid-conv" not in gw.calls[0]["messages"][0]["content"]
    assert "mid-conv" in gw.calls[1]["messages"][0]["content"]


# ---------- fire-and-forget reflection (storage layer phase 3) ----------


async def test_chat_done_fires_reflection_that_saves_memories():
    gw = FakeGateway(
        [assistant_msg("noted")],
        completions=[json.dumps({"memories": [
            {"text": "Owner prefers tabs", "type": "core", "importance": 6}]})])
    app, c = make_app_client(gw)
    async with c:
        r = await c.post("/api/chat", json={"conversation_id": "rf1",
                                            "message": "use tabs please"})
        events = [json.loads(line[6:]) for line in r.text.splitlines()
                  if line.startswith("data: ")]
        assert events[-1]["type"] == "done"
        await asyncio.gather(*app.state.switchgear.reflection_tasks)
        mems = await app.state.switchgear.storage.query("memories")
    assert [m["text"] for m in mems] == ["Owner prefers tabs"]
    assert mems[0]["source"] == "reflection"
    assert mems[0]["conversation_id"] == "rf1"
    assert gw.complete_calls and gw.complete_calls[0]["tier"] == "bulk"
    assert gw.complete_calls[0]["tools"] is None


async def test_reflection_failure_never_breaks_the_chat_response():
    gw = FakeGateway([assistant_msg("ok")],
                     completions=[RuntimeError("bulk model down")])
    app, c = make_app_client(gw)
    async with c:
        r = await c.post("/api/chat", json={"conversation_id": "rf2",
                                            "message": "hello"})
        events = [json.loads(line[6:]) for line in r.text.splitlines()
                  if line.startswith("data: ")]
        assert events[-1]["type"] == "done"  # the chat response completed cleanly
        # the wrapper swallows the failure: gather must not raise
        await asyncio.gather(*app.state.switchgear.reflection_tasks)
        assert await app.state.switchgear.storage.query("memories") == []
    # cursor untouched -> the turns are retried after the throttle window
    doc = await app.state.switchgear.storage.get("conversations", "rf2")
    assert "reflection_cursor" not in doc


async def test_second_turn_reflection_is_throttled():
    gw = FakeGateway([assistant_msg("one"), assistant_msg("two")],
                     completions=['{"memories": []}'])
    app, c = make_app_client(gw)
    async with c:
        await c.post("/api/chat", json={"conversation_id": "rf3", "message": "a"})
        await asyncio.gather(*app.state.switchgear.reflection_tasks)
        await c.post("/api/chat", json={"conversation_id": "rf3", "message": "b"})
        await asyncio.gather(*app.state.switchgear.reflection_tasks)
    # second turn landed inside the 600 s window: only one complete() call
    assert len(gw.complete_calls) == 1


# ---------- memory injection must degrade, never 500 the turn ----------


class CoreBlockRaises:
    async def core_block(self):
        raise RuntimeError("firestore down")

    async def recall(self, query, k=None):
        return []  # pragma: no cover - not reached; core_block raises first


class RecallRaises:
    async def core_block(self):
        return "- Always sign off with -D"

    async def recall(self, query, k=None):
        raise RuntimeError("embedder backfill write failed")


async def test_chat_survives_core_block_failure():
    gw = FakeGateway([assistant_msg("ok")])
    app, c = make_app_client(gw)
    app.state.switchgear.memory_store = CoreBlockRaises()
    async with c:
        r = await c.post("/api/chat", json={"conversation_id": "deg1", "message": "hi"})
        events = [json.loads(line[6:]) for line in r.text.splitlines()
                  if line.startswith("data: ")]
    assert events[-1]["type"] == "done"  # degraded, not a 500
    sysmsg = gw.calls[0]["messages"][0]["content"]
    assert "## Standing instructions (memories)" not in sysmsg
    assert "## Possibly relevant memories" not in sysmsg


async def test_chat_survives_recall_failure_and_drops_core_too():
    gw = FakeGateway([assistant_msg("ok")])
    app, c = make_app_client(gw)
    app.state.switchgear.memory_store = RecallRaises()
    async with c:
        r = await c.post("/api/chat", json={"conversation_id": "deg2", "message": "hi"})
        events = [json.loads(line[6:]) for line in r.text.splitlines()
                  if line.startswith("data: ")]
    assert events[-1]["type"] == "done"  # degraded, not a 500
    sysmsg = gw.calls[0]["messages"][0]["content"]
    # reset-both-on-except semantics: core_block succeeded but recall raised,
    # so the (already-fetched) core section is also dropped, not just recall's.
    assert "## Standing instructions (memories)" not in sysmsg
    assert "Always sign off with -D" not in sysmsg
    assert "## Possibly relevant memories" not in sysmsg


# ---------- email channel wiring (channels phase 1) ----------


def channel_app(storage=None, gateway=None, **kw):
    s = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3",
                 cron_secret="topsecret", **kw)
    return s, create_app(settings=s, gateway=gateway or FakeGateway([]),
                         storage=storage or MemoryStorage())


def _inbound(pid="m1"):
    return {"provider_id": pid, "thread_id": f"t-{pid}",
            "sender": "alice@example.com", "to": "agent@example.com",
            "subject": "Hi", "body": "hello", "body_is_html": False,
            "received_at": 1720000000.0}


async def test_lifespan_seeds_and_activates_email_channel():
    _, app = channel_app()
    async with app.router.lifespan_context(app):
        state = app.state.switchgear
        doc = await state.channel_store.get("email")
        assert doc is not None and doc["status"] == "active"
        assert set(state.channels) == {"email"}
        scheduled = await state.scheduler.list()
    assert any(x["skill"] == "poll-email" and x["cron"] == "*/5 * * * *"
               for x in scheduled)


async def test_channel_with_missing_workflow_is_skipped_not_fatal(tmp_path):
    ghost = tmp_path / "ghost"
    ghost.mkdir()
    (ghost / "CHANNEL.md").write_text(
        "---\nschema_version: 1\nname: ghost\ntransport: console\n"
        "workflow: does-not-exist\npoll_interval: 5m\n"
        "triage:\n  tier: bulk\n  routes:\n    file: {}\n---\nGhost.\n")
    _, app = channel_app(channels_dir=str(tmp_path))
    async with app.router.lifespan_context(app):
        state = app.state.switchgear
        assert (await state.channel_store.get("ghost"))["status"] == "active"
        assert state.channels == {}          # log + skip activation, no crash
        scheduled = await state.scheduler.list()
    assert not any(x["skill"] == "poll-ghost" for x in scheduled)


async def test_channel_schedule_provisioning_is_idempotent_across_reboots():
    storage = MemoryStorage()
    _, app1 = channel_app(storage=storage)
    async with app1.router.lifespan_context(app1):
        pass
    _, app2 = channel_app(storage=storage)
    counting = CountingScheduler(app2.state.switchgear.scheduler)
    app2.state.switchgear.scheduler = counting
    async with app2.router.lifespan_context(app2):
        pass
    assert counting.create_calls == []


async def test_channel_job_name_shadowed_by_existing_schedule_warns_and_skips(caplog):
    # A pre-existing schedule doc named "poll-email" (e.g. a skill of the same
    # name) targets a different endpoint than the channel poll job would. The
    # activation loop must not silently overwrite/skip it without a trace.
    _, app = channel_app()
    await app.state.switchgear.scheduler.create(
        name="poll-email", cron="* * * * *", skill="poll-email")
    async with app.router.lifespan_context(app):
        state = app.state.switchgear
        assert "email" in state.channels                # still activates
        scheduled = await state.scheduler.list()
    entry = next(s for s in scheduled if s["skill"] == "poll-email")
    assert entry["target_url"].endswith("/tasks/run-skill/poll-email")  # untouched
    assert any("shadowed" in rec.message and "poll-email" in rec.message
              for rec in caplog.records)


async def test_poll_channel_task_requires_cron_and_polls():
    from switchgear.channels.transport import ConsoleTransport

    # Scripted route:file completion: Phase 3 wires a real ChannelTriage into
    # every poll now, so the stored message no longer stays "pending" — it
    # gets classified synchronously inside poll(). Script a quiet "file"
    # route so this test keeps asserting the ingest/dedupe contract, not the
    # (separately-tested) triage classifier behavior.
    gw = FakeGateway([], completions=[
        json.dumps({"route": "file", "reason": "test message"})])
    _, app = channel_app(gateway=gw)
    async with app.router.lifespan_context(app):
        transport = app.state.switchgear.channels["email"]._transport
        assert isinstance(transport, ConsoleTransport)   # default backend
        transport.append_inbound(_inbound())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as c:
            r = await c.post("/tasks/poll-channel/email")
            assert r.status_code == 401                  # cron auth required
            r = await c.post("/tasks/poll-channel/email",
                             headers={"x-cron-secret": "topsecret"})
            assert r.json() == {"fetched": 1, "stored": 1, "duplicates": 0,
                                "failed": 0}
            r = await c.post("/tasks/poll-channel/nope",
                             headers={"x-cron-secret": "topsecret"})
            assert r.status_code == 404
        doc = await app.state.switchgear.storage.get("wf-channel-email-items",
                                                 message_key("m1"))
        assert doc["body_text"] == "hello"
        assert doc["triage_status"] == "routed"
        assert doc["triage_route"] == "file"


async def test_owner_poll_endpoint_is_owner_authed():
    s, app = channel_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as c:
            assert (await c.post("/api/channels/email/poll")).status_code == 401
            c.cookies.set("session", sign_session(s, "me@example.com"))
            r = await c.post("/api/channels/email/poll")
            assert r.json() == {"fetched": 0, "stored": 0, "duplicates": 0,
                                "failed": 0}
            assert (await c.post("/api/channels/nope/poll")).status_code == 404


async def test_cron_route_rejects_owner_session_cookie():
    # An owner session cookie alone must not satisfy require_cron -- the
    # cron task endpoint only accepts the shared secret or an OIDC token.
    s, app = channel_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as c:
            c.cookies.set("session", sign_session(s, "me@example.com"))
            r = await c.post("/tasks/poll-channel/email")
    assert r.status_code in (401, 403)


async def test_owner_route_rejects_cron_secret_header():
    # A cron shared-secret header alone must not satisfy require_owner -- the
    # owner-facing "poll now" endpoint only accepts a valid session cookie.
    _, app = channel_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as c:
            r = await c.post("/api/channels/email/poll",
                             headers={"x-cron-secret": "topsecret"})
    assert r.status_code == 401

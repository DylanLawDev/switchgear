from switchgear.storage.memory import MemoryStorage
from switchgear.tools.plan import make_plan_tool, plan_key_var, use_plan_key


async def test_set_then_read_round_trip():
    storage = MemoryStorage()
    tool = make_plan_tool(storage)
    with use_plan_key("conv-1"):
        result = await tool.handler(op="set", tasks=["find jobs", "tailor resume"],
                                    title="Job pipeline setup")
        assert result["title"] == "Job pipeline setup"
        assert [t["status"] for t in result["tasks"]] == ["pending", "pending"]
        read = await tool.handler(op="read")
    assert read["tasks"][0]["text"] == "find jobs"
    stored = await storage.get("plans", "conv-1")
    assert stored["tasks"][1]["text"] == "tailor resume"


async def test_check_updates_single_task_status():
    storage = MemoryStorage()
    tool = make_plan_tool(storage)
    with use_plan_key("conv-2"):
        await tool.handler(op="set", tasks=["a", "b"])
        result = await tool.handler(op="check", index=1, status="done")
    assert [t["status"] for t in result["tasks"]] == ["pending", "done"]


async def test_bounds_and_bad_input_rejected():
    storage = MemoryStorage()
    tool = make_plan_tool(storage)
    with use_plan_key("conv-3"):
        too_many = await tool.handler(op="set", tasks=[f"t{i}" for i in range(31)])
        assert "error" in too_many
        too_long = await tool.handler(op="set", tasks=["x" * 301])
        assert "error" in too_long
        await tool.handler(op="set", tasks=["a"])
        bad_index = await tool.handler(op="check", index=5, status="done")
        assert "error" in bad_index
        bad_status = await tool.handler(op="check", index=0, status="finished")
        assert "error" in bad_status
        no_plan = make_plan_tool(MemoryStorage())
        assert "error" in await no_plan.handler(op="check", index=0, status="done")
        assert "error" in await tool.handler(op="nope")


async def test_default_key_is_adhoc():
    storage = MemoryStorage()
    tool = make_plan_tool(storage)
    assert plan_key_var.get() == "adhoc"
    await tool.handler(op="set", tasks=["a"])
    assert await storage.get("plans", "adhoc") is not None


def test_format_plan_for_prompt():
    from switchgear.tools.plan import format_plan

    plan = {"title": "Setup", "tasks": [
        {"text": "a", "status": "done"},
        {"text": "b", "status": "in_progress"},
        {"text": "c", "status": "pending"},
        {"text": "d", "status": "skipped"},
    ]}
    text = format_plan(plan)
    assert "Setup" in text
    assert "- [x] a" in text
    assert "- [>] b" in text
    assert "- [ ] c" in text
    assert "- [-] d" in text
    assert format_plan(None) == ""


async def test_chat_injects_current_plan_into_system_prompt():
    import httpx

    from switchgear.auth import sign_session
    from switchgear.config import Settings
    from switchgear.web.app import create_app
    from tests.fakes import FakeGateway

    settings = Settings(_env_file=None, owner_email="me@example.com",
                        session_secret="s3", local_password_hash="scrypt:x")
    gw = FakeGateway([[{"type": "message", "usage": 1,
                        "message": {"role": "assistant", "content": "ok"}}]])
    app = create_app(settings=settings, gateway=gw, storage=MemoryStorage())
    await app.state.switchgear.storage.put("plans", "pc1", {
        "title": "Pipeline setup",
        "tasks": [{"text": "career bank", "status": "done"},
                  {"text": "workflow proposal", "status": "in_progress"}]})
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(settings, "me@example.com"))
    async with c:
        await c.post("/api/chat", json={"conversation_id": "pc1", "message": "go"})
    sysmsg = gw.calls[0]["messages"][0]["content"]
    assert "## Current plan" in sysmsg
    assert "- [x] career bank" in sysmsg
    assert "- [>] workflow proposal" in sysmsg

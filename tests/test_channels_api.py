import httpx

from switchgear.auth import sign_session
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from tests.fakes import FakeGateway

S = Settings(_env_file=None, owner_email="me@example.com", session_secret="s3")


def make_app():
    return create_app(settings=S, gateway=FakeGateway([]),
                      storage=MemoryStorage())


def client(app, authed=True):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t")
    if authed:
        c.cookies.set("session", sign_session(S, "me@example.com"))
    return c


# ---------- wiring ----------


async def test_create_app_wires_channel_send_layer():
    app = make_app()
    state = app.state.switchgear
    assert "channel-send" in state.workflow_plugins.executor_names
    assert state.sendfn_store is not None
    assert state.channel_send == {}                  # bound in lifespan
    assert "channel_messages" in state.registry._tools
    assert "channel_send" not in state.registry._tools  # born in lifespan


async def test_lifespan_activates_outbound_channel():
    app = make_app()
    async with app.router.lifespan_context(app):
        state = app.state.switchgear
        wf = await state.workflow_store.get("channel-email")
        assert wf is not None and wf["status"] == "active"
        assert wf["actions"]["executor"] == "channel-send"
        assert wf["actions"]["approval_ttl"] == 3 * 86400
        assert "email" in state.channel_send
        executor = state.workflow_plugins.executor("channel-send")
        assert executor.send_service is state.channel_send["email"]
        assert "channel_send" in state.registry._tools


# ---------- routes: auth ----------

FN = {
    "description": "cold outreach",
    "params": {"role": {"type": "string", "max_chars": 120}},
    "subject_template": "Regarding {{role}}",
    "body_template": "Hello, about the {{role}} role.",
    "recipient_rule": {"type": "fixed", "address": "VIP@Corp.com"},
    "gate": "approve",
}


async def test_channel_routes_require_owner_auth():
    app = make_app()
    async with client(app, authed=False) as c:
        assert (await c.get("/api/channels/email")).status_code == 401
        assert (await c.get("/api/channels/email/send-functions")).status_code == 401
        assert (await c.get("/api/channels/email/send-functions/x")).status_code == 401
        assert (await c.put("/api/channels/email/send-functions/x",
                            json=FN)).status_code == 401
        assert (await c.delete("/api/channels/email/send-functions/x")).status_code == 401
        assert (await c.get("/api/channels/email/suppression")).status_code == 401
        assert (await c.put("/api/channels/email/suppression/a@b.com")).status_code == 401
        assert (await c.delete("/api/channels/email/suppression/a@b.com")).status_code == 401
        r = await c.get("/channels/email", headers={"accept": "text/html"},
                        follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == "/login"


async def test_channels_page_renders_shell():
    app = make_app()
    async with client(app) as c:
        r = await c.get("/channels/email")
    assert r.status_code == 200
    assert "channels.js" in r.text
    assert 'class="tab active" data-tab="channels"' in r.text


async def test_channel_status_endpoint():
    app = make_app()
    async with app.router.lifespan_context(app):
        async with client(app) as c:
            r = await c.get("/api/channels/email")
            assert r.status_code == 200
            body = r.json()
            assert body["name"] == "email"
            assert body["active"] is True
            for field in ("address", "transport", "cursor", "last_poll"):
                assert field in body
            assert body["last_poll"] is None    # never polled yet
            assert (await c.get("/api/channels/nope")).status_code == 404


async def test_channel_status_carries_last_poll_after_a_real_poll():
    app = make_app()
    async with app.router.lifespan_context(app):
        async with client(app) as c:
            poll = await c.post("/api/channels/email/poll")
            assert poll.status_code == 200
            body = (await c.get("/api/channels/email")).json()
            assert body["last_poll"] is not None


# ---------- routes: send functions ----------


async def test_send_function_crud_roundtrip():
    app = make_app()
    async with client(app) as c:
        r = await c.put("/api/channels/email/send-functions/outreach", json=FN)
        assert r.status_code == 200
        doc = r.json()
        assert doc["name"] == "outreach"                      # name from path
        assert doc["recipient_rule"]["address"] == "vip@corp.com"
        assert doc["rate_limit_per_day"] == 5 and doc["enabled"] is True

        rows = (await c.get("/api/channels/email/send-functions")).json()
        assert [row["name"] for row in rows] == ["outreach"]

        one = (await c.get("/api/channels/email/send-functions/outreach")).json()
        assert one["subject_template"] == FN["subject_template"]
        assert (await c.get("/api/channels/email/send-functions/nope")
                ).status_code == 404

        assert (await c.delete("/api/channels/email/send-functions/outreach")
                ).json() == {"ok": True}
        assert (await c.delete("/api/channels/email/send-functions/outreach")
                ).status_code == 404


async def test_send_function_validation_errors_are_400_with_message():
    app = make_app()
    async with client(app) as c:
        r = await c.put("/api/channels/email/send-functions/outreach",
                        json={**FN, "gate": "auto"})
        assert r.status_code == 400
        assert "cold outbound" in r.json()["detail"]
        r = await c.put("/api/channels/email/send-functions/outreach",
                        json={**FN, "subject_template": "Hi {{whom}}"})
        assert r.status_code == 400
        assert "unknown slot" in r.json()["detail"]


# ---------- routes: suppression ----------


async def test_suppression_crud_normalizes_and_validates():
    app = make_app()
    async with client(app) as c:
        r = await c.put("/api/channels/email/suppression/Spam%40Evil.com")
        assert r.status_code == 200 and r.json() == {"address": "spam@evil.com"}
        rows = (await c.get("/api/channels/email/suppression")).json()
        assert [row["address"] for row in rows] == ["spam@evil.com"]
        assert "added_at" in rows[0]
        assert (await c.put("/api/channels/email/suppression/junk")
                ).status_code == 400
        assert (await c.delete("/api/channels/email/suppression/spam@evil.com")
                ).json() == {"ok": True}
        assert (await c.delete("/api/channels/email/suppression/spam@evil.com")
                ).status_code == 404


async def test_channel_writes_are_audited():
    app = make_app()
    async with client(app) as c:
        await c.put("/api/channels/email/send-functions/outreach", json=FN)
        await c.delete("/api/channels/email/send-functions/outreach")
        await c.put("/api/channels/email/suppression/spam@evil.com")
        await c.delete("/api/channels/email/suppression/spam@evil.com")
    actions = [a.get("action") for a in
               await app.state.switchgear.storage.query("audit")]
    for expected in ("sendfn_save", "sendfn_delete",
                     "suppression_add", "suppression_remove"):
        assert expected in actions

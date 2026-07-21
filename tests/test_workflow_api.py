import time

import httpx

from switchgear.auth import sign_session
from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.web.app import create_app
from switchgear.workflows.actions import DraftResult

OWNER = "me@example.com"

TESTFLOW = """---
schema_version: 1
name: test-flow
description: a test workflow
items:
  label: thing
  label_plural: things
  title_field: title
  retention: 90d
  expected_update_period: 2d
  fields:
    title:    {type: text}
    score:    {type: score, max: 100}
    url:      {type: url}
    found_at: {type: timestamp}
  list_fields: [title, score, found_at]
  sort: [-score, -found_at]
artifacts:
  label: brief
  label_plural: briefs
  title_field: title
  fields:
    title:      {type: text}
    body:       {type: markdown}
    created_at: {type: timestamp}
actions:
  label: dispatch
  label_plural: dispatches
  executor: fake-exec
intake:
  skills: [test-intake]
---
Body.
"""


class FakeExecutor:
    async def draft(self, item):
        return DraftResult(fields=[{"selector": "#a", "label": "A", "value": "x",
                                    "source": "profile", "needs_you": False,
                                    "kind": "text"}])

    async def execute(self, record):
        return {}


class FakeGenerator:
    def __init__(self):
        self.calls = []

    async def generate(self, wf, item):
        self.calls.append((wf["name"], item["key"]))
        return {"ok": True, "generated_for": item["key"]}


def make_app(tmp_path):
    settings = Settings(_env_file=None, owner_email=OWNER, session_secret="s3",
                        state_dir=str(tmp_path / "state"),
                        career_dir=str(tmp_path / "no-bank"))
    return create_app(settings=settings, storage=MemoryStorage())


async def wire(app, text=TESTFLOW):
    state = app.state.switchgear
    state.workflow_plugins.register_executor("fake-exec", FakeExecutor())
    gen = FakeGenerator()
    state.workflow_plugins.register_generator("fake-gen", gen)
    await state.workflow_store.save(text, source="repo")
    return gen


def client(app):
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    c.cookies.set("session", sign_session(app.state.switchgear.settings, OWNER))
    return c


async def seed_item(app, key="itm-1", title="Thing One", score=80, found_at=None):
    await app.state.switchgear.storage.put("wf-test-flow-items", key, {
        "key": key, "title": title, "score": score, "url": "https://x.example",
        "found_at": found_at if found_at is not None else time.time()})


# ---------- GET /api/workflows ----------


async def test_list_workflows_active_only_with_staleness(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    # no ok run for test-intake ever -> stale (period 2d)
    async with client(app) as c:
        r = await c.get("/api/workflows")
    assert r.status_code == 200
    rows = r.json()
    assert rows[0]["name"] == "test-flow"
    assert rows[0]["stale"] is True


async def test_list_workflows_fresh_run_not_stale(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    await app.state.switchgear.storage.put("runs", "r1", {
        "skill": "test-intake", "ok": True, "at": time.time()})
    async with client(app) as c:
        rows = (await c.get("/api/workflows")).json()
    assert rows[0]["stale"] is False


async def test_ui_home_in_summaries_and_definition(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    async with client(app) as c:
        rows = (await c.get("/api/workflows")).json()
        assert all(r["ui_home"] in ("workflows", "channels") for r in rows)
        one = (await c.get(f"/api/workflows/{rows[0]['name']}")).json()
    assert "ui_home" in one


# ---------- GET /api/workflows/{name} ----------


async def test_get_definition_and_404(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    async with client(app) as c:
        r = await c.get("/api/workflows/test-flow")
        missing = await c.get("/api/workflows/nope")
    assert r.status_code == 200
    body = r.json()
    assert body["items"]["fields"]["score"]["type"] == "score"
    assert body["actions"]["label"] == "dispatch"
    assert "executor" in body["actions"]
    assert missing.status_code == 404


# ---------- GET /workflows/{name} (definition embed hardening) ----------


XSS_WORKFLOW = TESTFLOW.replace(
    "description: a test workflow",
    'description: "desc </script><script>alert(1)</script> and <!--<script>-->"',
).replace(
    "Body.",
    "Body with </script><script>alert(2)</script> and <!--<script> embedded.",
)


async def test_workflow_page_escapes_all_angle_brackets_in_definition(tmp_path):
    app = make_app(tmp_path)
    await wire(app, text=XSS_WORKFLOW)
    async with client(app) as c:
        r = await c.get("/workflows/test-flow")
    assert r.status_code == 200
    payload = r.text.split('id="wf-def">', 1)[1].split("</script>", 1)[0]
    assert "<" not in payload
    assert "\\u003cscript>" in payload
    assert "\\u003c!--" in payload


# ---------- GET /api/workflows/{name}/{kind} ----------


async def test_items_sorted_by_definition_none_scores_last(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    # found_at values are within retention (90d) so the sort test isn't
    # confounded by the lazy purge; they only differ enough to keep sort
    # a well-defined tiebreaker (score is the actual differentiator below).
    now = time.time()
    await seed_item(app, "itm-low", score=10, found_at=now - 3.0)
    await seed_item(app, "itm-high", score=90, found_at=now - 1.0)
    await seed_item(app, "itm-none", score=None, found_at=now - 2.0)
    async with client(app) as c:
        rows = (await c.get("/api/workflows/test-flow/items")).json()
    assert [r["key"] for r in rows] == ["itm-high", "itm-low", "itm-none"]


async def test_items_retention_filters_old_records_without_mutating_on_get(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    await seed_item(app, "itm-old", found_at=time.time() - 91 * 86400)
    await seed_item(app, "itm-new")
    async with client(app) as c:
        rows = (await c.get("/api/workflows/test-flow/items")).json()
    assert [r["key"] for r in rows] == ["itm-new"]
    assert await app.state.switchgear.storage.get("wf-test-flow-items", "itm-old") is not None


async def test_actions_list_shaped_with_item_title(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    await seed_item(app)
    state = app.state.switchgear
    wf = await state.workflow_store.get("test-flow")
    rec = await state.gated_actions.start_draft(wf, "itm-1")
    async with client(app) as c:
        rows = (await c.get("/api/workflows/test-flow/actions")).json()
    assert rows[0]["key"] == rec["key"]
    assert rows[0]["item"] == {"key": "itm-1", "title": "Thing One"}
    assert rows[0]["status"] == "draft"
    assert rows[0]["needs_you"] == 0


async def test_artifact_list_row_omits_undeclared_field_but_detail_keeps_it(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    await seed_item(app)
    state = app.state.switchgear
    await state.storage.put("wf-test-flow-artifacts", "art-1", {
        "key": "art-1", "item_key": "itm-1", "title": "Brief", "body": "# hi",
        "created_at": 5.0, "selection": {"huge": "payload"}})
    async with client(app) as c:
        rows = (await c.get("/api/workflows/test-flow/artifacts")).json()
        detail = (await c.get("/api/workflows/test-flow/artifacts/art-1")).json()
    assert "selection" not in rows[0]
    assert rows[0] == {"key": "art-1", "item_key": "itm-1", "title": "Brief",
                       "body": "# hi", "created_at": 5.0}
    assert detail["record"]["selection"] == {"huge": "payload"}


async def test_unknown_kind_and_undefined_kind_404(tmp_path):
    app = make_app(tmp_path)
    intake_only = TESTFLOW.split("artifacts:")[0] + "intake:\n  skills: []\n---\nBody.\n"
    await wire(app, text=intake_only)
    async with client(app) as c:
        assert (await c.get("/api/workflows/test-flow/bogus")).status_code == 404
        assert (await c.get("/api/workflows/test-flow/actions")).status_code == 404


# ---------- GET /api/workflows/{name}/{kind}/{key} ----------


async def test_item_detail_includes_lineage(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    await seed_item(app)
    state = app.state.switchgear
    await state.storage.put("wf-test-flow-artifacts", "art-1", {
        "key": "art-1", "item_key": "itm-1", "title": "Brief", "body": "# hi",
        "created_at": 5.0})
    wf = await state.workflow_store.get("test-flow")
    action = await state.gated_actions.start_draft(wf, "itm-1")
    async with client(app) as c:
        r = await c.get("/api/workflows/test-flow/items/itm-1")
    body = r.json()
    assert body["record"]["title"] == "Thing One"
    assert body["artifacts"][0]["key"] == "art-1"
    assert body["actions"][0]["key"] == action["key"]


async def test_action_detail_returns_record_and_item(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    await seed_item(app)
    state = app.state.switchgear
    wf = await state.workflow_store.get("test-flow")
    action = await state.gated_actions.start_draft(wf, "itm-1")
    async with client(app) as c:
        r = await c.get(f"/api/workflows/test-flow/actions/{action['key']}")
    body = r.json()
    assert body["record"]["fields"][0]["selector"] == "#a"
    assert body["item"]["title"] == "Thing One"


async def test_record_detail_404s(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    async with client(app) as c:
        assert (await c.get("/api/workflows/test-flow/items/nope")).status_code == 404


# ---------- auth ----------


async def test_non_active_workflow_404s_on_generic_api(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    await seed_item(app)
    state = app.state.switchgear
    await state.workflow_store.set_status("test-flow", "pending")
    async with client(app) as c:
        assert (await c.get("/api/workflows/test-flow")).status_code == 404
        assert (await c.post(
            "/api/workflows/test-flow/items/itm-1/act")).status_code == 404


async def test_workflow_api_requires_auth(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        assert (await c.get("/api/workflows")).status_code == 401
        assert (await c.get("/api/workflows/test-flow")).status_code == 401
        assert (await c.get("/api/workflows/test-flow/items")).status_code == 401
        assert (await c.get("/api/workflows/test-flow/items/x")).status_code == 401


# ---------- verbs ----------


async def test_generate_delegates_to_registered_generator(tmp_path):
    app = make_app(tmp_path)
    gen = await wire(app, text=TESTFLOW.replace(
        "intake:", "generate:\n  plugin: fake-gen\n  label: Write brief\nintake:"))
    await seed_item(app)
    async with client(app) as c:
        r = await c.post("/api/workflows/test-flow/items/itm-1/generate")
    assert r.json() == {"ok": True, "generated_for": "itm-1"}
    assert gen.calls == [("test-flow", "itm-1")]


async def test_generate_without_generator_errors(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    await seed_item(app)
    async with client(app) as c:
        r = await c.post("/api/workflows/test-flow/items/itm-1/generate")
    assert r.json() == {"error": "no generator configured"}


async def test_generate_missing_item_404(tmp_path):
    app = make_app(tmp_path)
    await wire(app, text=TESTFLOW.replace(
        "intake:", "generate:\n  plugin: fake-gen\n  label: Write brief\nintake:"))
    async with client(app) as c:
        assert (await c.post(
            "/api/workflows/test-flow/items/nope/generate")).status_code == 404


async def test_act_then_full_action_lifecycle_via_api(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    await seed_item(app)
    async with client(app) as c:
        draft = (await c.post("/api/workflows/test-flow/items/itm-1/act")).json()
        key = draft["key"]
        assert draft["status"] == "draft"

        upd = (await c.post(f"/api/workflows/test-flow/actions/{key}/fields", json={
            "fields": [{"selector": "#a", "value": "edited", "needs_you": False}]})).json()
        assert upd["fields"][0]["value"] == "edited"

        approved = (await c.post(
            f"/api/workflows/test-flow/actions/{key}/approve")).json()
        assert approved["status"] == "approved"
        assert approved["approval"]["approved_by"] == OWNER

        executed = (await c.post(
            f"/api/workflows/test-flow/actions/{key}/execute")).json()
        assert executed["status"] == "executed"


async def test_reject_requires_comment_via_api(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    await seed_item(app)
    async with client(app) as c:
        draft = (await c.post("/api/workflows/test-flow/items/itm-1/act")).json()
        r = await c.post(f"/api/workflows/test-flow/actions/{draft['key']}/reject",
                         json={"comment": "not this one"})
    assert r.json()["status"] == "rejected"
    assert r.json()["rejected_comment"] == "not this one"


async def test_confirm_endpoint_resolves_possibly_executed(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    await seed_item(app)
    state = app.state.switchgear

    class AmbiguousExecutor(FakeExecutor):
        async def execute(self, record):
            from switchgear.workflows.actions import ExecutionAmbiguous
            raise ExecutionAmbiguous("click lost")

    state.workflow_plugins.register_executor("fake-exec", AmbiguousExecutor())
    async with client(app) as c:
        draft = (await c.post("/api/workflows/test-flow/items/itm-1/act")).json()
        key = draft["key"]
        await c.post(f"/api/workflows/test-flow/actions/{key}/approve")
        out = (await c.post(f"/api/workflows/test-flow/actions/{key}/execute")).json()
        assert out["status"] == "possibly_executed"
        confirmed = (await c.post(f"/api/workflows/test-flow/actions/{key}/confirm",
                                  json={"outcome": "executed"})).json()
    assert confirmed["status"] == "executed"


async def test_action_verbs_404_on_missing(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    async with client(app) as c:
        for verb, body in (("fields", {"fields": []}), ("approve", None),
                           ("reject", {"comment": "x"}), ("execute", None),
                           ("confirm", {"outcome": "failed"})):
            kwargs = {"json": body} if body is not None else {}
            r = await c.post(f"/api/workflows/test-flow/actions/nope/{verb}", **kwargs)
            assert r.status_code == 404, verb


async def test_verb_routes_require_auth(tmp_path):
    app = make_app(tmp_path)
    await wire(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t") as c:
        assert (await c.post(
            "/api/workflows/test-flow/items/x/act")).status_code == 401
        assert (await c.post(
            "/api/workflows/test-flow/actions/x/approve")).status_code == 401

"""Generic workflow API + page routes. One set of routes serves every
workflow; the definition drives shapes and sorting. Registered from
create_app in closure style."""

import json

from fastapi import Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from switchgear import auth
from switchgear.web.spa import spa_index, spa_response

KINDS = ("items", "artifacts", "actions")


class FieldUpdate(BaseModel):
    selector: str
    value: str
    needs_you: bool


class FieldsRequest(BaseModel):
    fields: list[FieldUpdate]


class RejectRequest(BaseModel):
    comment: str


class ConfirmRequest(BaseModel):
    outcome: str


def public_definition(wf: dict) -> dict:
    return {k: wf.get(k) for k in
            ("name", "description", "ui_home", "body", "items", "artifacts",
             "actions", "generate", "intake", "execution", "schema_version", "text")}


def sort_records(records: list[dict], sort_spec: list[str]) -> None:
    """Numeric sort per definition; None values always last (matches the old
    jobs page). Sort keys are validated numeric/timestamp at parse time."""
    for spec in reversed(sort_spec):
        desc = spec.startswith("-")
        fname = spec.lstrip("-")

        def key(r, f=fname, d=desc):
            v = r.get(f)
            if not isinstance(v, (int, float)):
                v = None
            return (v is None, -(v or 0) if d else (v or 0))

        records.sort(key=key)


def register_workflow_routes(app, state, jinja, nav) -> None:
    storage = state.storage

    async def _wf_or_404(name: str) -> dict:
        wf = await state.workflow_store.get(name)
        if wf is None or wf.get("status") != "active":
            raise StarletteHTTPException(404, "workflow not found")
        return wf

    def _kind_or_404(wf: dict, kind: str) -> dict:
        if kind not in KINDS or not wf.get(kind):
            raise StarletteHTTPException(404, "unknown kind")
        return wf[kind]

    async def _item_title(wf: dict, item_key: str | None) -> dict | None:
        if not item_key or not wf.get("items"):
            return None
        item = await storage.get(wf["items"]["collection"], item_key)
        if item is None:
            return None
        return {"key": item_key, "title": item.get(wf["items"]["title_field"])}

    def _shape_row(kdef: dict, record: dict, extra_keys: tuple[str, ...] = ()) -> dict:
        keys = (kdef["key_field"], *extra_keys, *kdef["fields"].keys())
        return {k: record.get(k) for k in keys}

    def _action_row(wf: dict, r: dict, item: dict | None) -> dict:
        return {"key": r.get(wf["actions"]["key_field"]),
                "item": item,
                "status": r.get("status"),
                "needs_you": sum(1 for f in r.get("fields", []) if f.get("needs_you")),
                "created_at": r.get("created_at")}

    # ---------- page ----------

    @app.get("/w/{name}")
    async def legacy_workflow_page(name: str):
        return RedirectResponse(f"/workflows/{name}", status_code=301)

    @app.get("/workflows", response_class=HTMLResponse)
    async def workflows_index(email: str = Depends(auth.require_owner)):
        if spa_index():
            return spa_response()
        for row in await nav():
            if row.get("ui_home", "workflows") == "workflows":
                return RedirectResponse(f"/workflows/{row['name']}",
                                        status_code=307)
        return RedirectResponse("/", status_code=307)

    @app.get("/workflows/{name}", response_class=HTMLResponse)
    async def workflow_page(name: str, email: str = Depends(auth.require_owner)):
        if spa_index():
            return spa_response()
        wf = await state.workflow_store.get(name)
        if wf is None or wf.get("status") != "active":
            raise StarletteHTTPException(404, "workflow not found")
        definition_json = json.dumps(public_definition(wf)).replace("<", "\\u003c")
        return jinja.get_template("workflow.html").render(
            owner=email, active=f"wf:{name}", workflows=await nav(),
            wf_name=name, wf_description=wf["description"],
            definition_json=definition_json)

    # ---------- reads ----------

    @app.get("/api/workflows")
    async def list_workflows(email: str = Depends(auth.require_owner)):
        return await nav()

    @app.get("/api/workflows/{name}")
    async def get_workflow(name: str, email: str = Depends(auth.require_owner)):
        return public_definition(await _wf_or_404(name))

    @app.get("/api/workflows/{name}/{kind}")
    async def list_kind(name: str, kind: str, email: str = Depends(auth.require_owner)):
        wf = await _wf_or_404(name)
        kdef = _kind_or_404(wf, kind)
        if kind == "actions":
            rows = []
            for r in await state.gated_actions.list(wf):
                item = await _item_title(wf, r.get(wf["actions"]["item_ref_field"]))
                rows.append(_action_row(wf, r, item))
            return rows
        records = await storage.query(kdef["collection"])
        if kind == "items":
            records = state.workflow_store.filter_expired_items(wf, records)
        sort_records(records, kdef["sort"])
        extra_keys = (kdef["item_ref_field"],) if kind == "artifacts" else ()
        return [_shape_row(kdef, r, extra_keys) for r in records[:200]]

    @app.get("/api/workflows/{name}/{kind}/{key}")
    async def get_record(name: str, kind: str, key: str,
                         email: str = Depends(auth.require_owner)):
        wf = await _wf_or_404(name)
        kdef = _kind_or_404(wf, kind)
        if kind == "actions":
            record = await state.gated_actions.get(wf, key)
        else:
            record = await storage.get(kdef["collection"], key)
        if record is None:
            raise StarletteHTTPException(404, f"{kdef['label']} not found")
        if kind == "items":
            artifacts, actions = [], []
            if wf.get("artifacts"):
                artifacts = await storage.query(
                    wf["artifacts"]["collection"],
                    where={wf["artifacts"]["item_ref_field"]: key})
                sort_records(artifacts, wf["artifacts"]["sort"])
            if wf.get("actions"):
                for r in await state.gated_actions.list(wf):
                    if r.get(wf["actions"]["item_ref_field"]) == key:
                        actions.append(_action_row(wf, r, {"key": key, "title": None}))
            return {"record": record, "artifacts": artifacts, "actions": actions}
        item = await _item_title(wf, record.get(kdef["item_ref_field"]))
        return {"record": record, "item": item}

    # ---------- verbs ----------

    @app.post("/api/workflows/{name}/items/{key}/generate")
    async def generate(name: str, key: str, email: str = Depends(auth.require_owner)):
        wf = await _wf_or_404(name)
        if not wf.get("generate"):
            return {"error": "no generator configured"}
        item = await storage.get(wf["items"]["collection"], key)
        if item is None:
            raise StarletteHTTPException(404, f"{wf['items']['label']} not found")
        generator = state.workflow_plugins.generator(wf["generate"]["plugin"])
        return await generator.generate(wf, item)

    @app.post("/api/workflows/{name}/items/{key}/act")
    async def act(name: str, key: str, email: str = Depends(auth.require_owner)):
        wf = await _wf_or_404(name)
        if not wf.get("actions"):
            return {"error": "no actions configured"}
        return await state.gated_actions.start_draft(wf, key)

    async def _action_verb(name: str, coro_factory):
        wf = await _wf_or_404(name)
        if not wf.get("actions"):
            raise StarletteHTTPException(404, "no actions configured")
        record = await coro_factory(wf)
        if record is None:
            raise StarletteHTTPException(404, f"{wf['actions']['label']} not found")
        return record

    @app.post("/api/workflows/{name}/actions/{key}/fields")
    async def action_fields(name: str, key: str, body: FieldsRequest,
                            email: str = Depends(auth.require_owner)):
        return await _action_verb(name, lambda wf: state.gated_actions.update_fields(
            wf, key, [f.model_dump() for f in body.fields]))

    @app.post("/api/workflows/{name}/actions/{key}/approve")
    async def action_approve(name: str, key: str,
                             email: str = Depends(auth.require_owner)):
        return await _action_verb(name, lambda wf: state.gated_actions.approve(
            wf, key, approved_by=email))

    @app.post("/api/workflows/{name}/actions/{key}/reject")
    async def action_reject(name: str, key: str, body: RejectRequest,
                            email: str = Depends(auth.require_owner)):
        return await _action_verb(name, lambda wf: state.gated_actions.reject(
            wf, key, comment=body.comment))

    @app.post("/api/workflows/{name}/actions/{key}/execute")
    async def action_execute(name: str, key: str,
                             email: str = Depends(auth.require_owner)):
        return await _action_verb(name, lambda wf: state.gated_actions.execute(wf, key))

    @app.post("/api/workflows/{name}/actions/{key}/confirm")
    async def action_confirm(name: str, key: str, body: ConfirmRequest,
                             email: str = Depends(auth.require_owner)):
        return await _action_verb(name, lambda wf: state.gated_actions.confirm(
            wf, key, outcome=body.outcome))

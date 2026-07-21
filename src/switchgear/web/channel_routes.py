"""Channel poll endpoints (spec §4.1). The cron task mirrors /tasks/run-skill
(require_cron: shared secret or OIDC audience = service_url); the /api variant
is the owner-authed "Poll now" target for the Phase 2 UI."""

import time
from uuid import uuid4

from fastapi import Body, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from switchgear import auth
from switchgear.channels.send import SUPPRESSION_COLLECTION, normalize_address
from switchgear.channels.sendfns import EMAIL_RE, SendFunctionError
from switchgear.web.cron import require_cron
from switchgear.web.spa import spa_index, spa_response


def register_channel_routes(app, state, jinja, nav) -> None:
    def _ingest(name: str):
        ingest = state.channels.get(name)
        if ingest is None:
            raise StarletteHTTPException(404, "channel not found")
        return ingest

    @app.post("/tasks/poll-channel/{name}")
    async def poll_channel_task(name: str, _: str = Depends(require_cron)):
        return await _ingest(name).poll()

    @app.post("/api/channels/{name}/poll")
    async def poll_channel_owner(name: str,
                                 email: str = Depends(auth.require_owner)):
        return await _ingest(name).poll()

    # ---------- channel page + status (spec §6) ----------

    @app.get("/channels", response_class=HTMLResponse)
    async def channels_index(email: str = Depends(auth.require_owner)):
        if spa_index():
            return spa_response()
        return RedirectResponse("/channels/email", status_code=307)

    @app.get("/channels/{name}", response_class=HTMLResponse)
    async def channel_page(name: str, email: str = Depends(auth.require_owner)):
        if spa_index():
            return RedirectResponse("/channels", status_code=301)
        # A pure shell (like every other page): data comes from the APIs,
        # and tests exercise pages without running lifespan seeding — so no
        # channel-existence check here.
        return jinja.get_template("channels.html").render(
            owner=email, active="channels", workflows=await nav(),
            channel_name=name)

    @app.get("/api/channels/{name}")
    async def channel_status(name: str,
                             email: str = Depends(auth.require_owner)):
        channel = await state.channel_store.get(name)
        if channel is None:
            raise StarletteHTTPException(404, "channel not found")
        st = await state.storage.get("channel-state", name) or {}
        return {"name": name, "address": channel.get("address"),
                "transport": channel.get("transport"),
                "active": name in state.channels,
                "cursor": st.get("cursor"), "last_poll": st.get("last_poll")}

    # ---------- send functions (spec §5.1, §6) ----------

    @app.get("/api/channels/{name}/send-functions")
    async def list_send_functions(name: str,
                                  email: str = Depends(auth.require_owner)):
        return await state.sendfn_store.list()

    @app.get("/api/channels/{name}/send-functions/{fn}")
    async def get_send_function(name: str, fn: str,
                                email: str = Depends(auth.require_owner)):
        doc = await state.sendfn_store.get(fn)
        if doc is None:
            raise StarletteHTTPException(404, "send function not found")
        return doc

    @app.put("/api/channels/{name}/send-functions/{fn}")
    async def put_send_function(name: str, fn: str, body: dict = Body(...),
                                email: str = Depends(auth.require_owner)):
        try:
            return await state.sendfn_store.save({**body, "name": fn},
                                                 source="user")
        except SendFunctionError as e:
            raise StarletteHTTPException(400, str(e)) from None

    @app.delete("/api/channels/{name}/send-functions/{fn}")
    async def delete_send_function(name: str, fn: str,
                                   email: str = Depends(auth.require_owner)):
        if not await state.sendfn_store.delete(fn):
            raise StarletteHTTPException(404, "send function not found")
        return {"ok": True}

    # ---------- suppression list (spec §5.2 step 4, §6) ----------
    # Global collection: addresses get suppressed, not channel-address pairs;
    # the channel-scoped path exists for URL symmetry with the editor page.

    @app.get("/api/channels/{name}/suppression")
    async def list_suppression(name: str,
                               email: str = Depends(auth.require_owner)):
        rows = await state.storage.query(SUPPRESSION_COLLECTION)
        rows.sort(key=lambda r: r.get("address") or "")
        return [{"address": r.get("address"), "added_at": r.get("added_at")}
                for r in rows]

    @app.put("/api/channels/{name}/suppression/{address}")
    async def add_suppression(name: str, address: str,
                              email: str = Depends(auth.require_owner)):
        addr = normalize_address(address)
        if not EMAIL_RE.fullmatch(addr):
            raise StarletteHTTPException(400, f"invalid address {address!r}")
        await state.storage.put(SUPPRESSION_COLLECTION, addr,
                                {"address": addr, "added_at": time.time()})
        await state.storage.put("audit", f"chsup-{uuid4().hex}", {
            "action": "suppression_add", "address": addr, "at": time.time()})
        return {"address": addr}

    @app.delete("/api/channels/{name}/suppression/{address}")
    async def remove_suppression(name: str, address: str,
                                 email: str = Depends(auth.require_owner)):
        addr = normalize_address(address)
        if await state.storage.get(SUPPRESSION_COLLECTION, addr) is None:
            raise StarletteHTTPException(404, "address not suppressed")
        await state.storage.delete(SUPPRESSION_COLLECTION, addr)
        await state.storage.put("audit", f"chsup-{uuid4().hex}", {
            "action": "suppression_remove", "address": addr,
            "at": time.time()})
        return {"ok": True}

    # ---------- flagged triage queue + refile (spec §7, Phase 3) ----------

    class RefileRequest(BaseModel):
        route: str

    async def _channel_items(name: str) -> tuple[dict, dict]:
        channel = await state.channel_store.get(name)
        if channel is None:
            raise StarletteHTTPException(404, "channel not found")
        wf = await state.workflow_store.get(channel["workflow"])
        if wf is None:
            raise StarletteHTTPException(404, "channel workflow not found")
        return channel, wf

    @app.get("/api/channels/{name}/flagged")
    async def flagged_messages(name: str, email: str = Depends(auth.require_owner)):
        _channel, wf = await _channel_items(name)
        kf = wf["items"]["key_field"]
        docs = await state.storage.query(wf["items"]["collection"],
                                         where={"triage_status": "flagged"})
        docs.sort(key=lambda d: d.get("received_at") or 0, reverse=True)
        # Metadata ONLY: the body is untrusted text and stays off this surface.
        return [{"key": d.get(kf), "subject": d.get("subject"),
                 "sender": d.get("sender"), "received_at": d.get("received_at"),
                 "triage_reason": d.get("triage_reason")} for d in docs]

    @app.post("/api/channels/{name}/messages/{key}/refile")
    async def refile_message(name: str, key: str, body: RefileRequest,
                             email: str = Depends(auth.require_owner)):
        # Deterministic, no model: the ONLY owner action here is "file it".
        if body.route != "file":
            raise StarletteHTTPException(400, "route must be 'file'")
        _channel, wf = await _channel_items(name)
        coll = wf["items"]["collection"]
        doc = await state.storage.get(coll, key)
        if doc is None:
            raise StarletteHTTPException(404, "message not found")
        if doc.get("triage_status") != "flagged":
            raise StarletteHTTPException(409, "message is not flagged")
        doc["triage_route"] = "file"
        doc["triage_status"] = "routed"
        doc["triage_reason"] = "refiled by owner"
        await state.storage.put(coll, key, doc)
        await state.storage.put("audit", f"tri-{uuid4().hex}", {
            "action": "channel_refile", "channel": name, "key": key,
            "route": "file", "actor": email, "at": time.time()})
        return {"key": key, "triage_status": "routed", "triage_route": "file"}

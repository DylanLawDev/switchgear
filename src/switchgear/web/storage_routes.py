"""Resource management: /resources page + owner-authed CRUD API (spec §4.4).
Registered from create_app in closure style, mirroring workflow_routes.
Phase 2 of the storage epic adds the /memories page + API here."""

from fastapi import Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from switchgear import auth
from switchgear.memory.store import MemoryError
from switchgear.resources.store import ResourceError
from switchgear.web.spa import spa_index, spa_response


class ResourcePutRequest(BaseModel):
    kind: str
    description: str = ""
    content: str


class MemoryCreateRequest(BaseModel):
    text: str
    type: str
    importance: int = 5


class MemoryTextRequest(BaseModel):
    text: str


class WriteModeRequest(BaseModel):
    write_mode: str


def register_storage_routes(app, state, jinja, nav) -> None:
    @app.get("/resources", response_class=HTMLResponse)
    async def resources_page(email: str = Depends(auth.require_owner)):
        if spa_index():
            return spa_response()
        return jinja.get_template("resources.html").render(
            owner=email, active="resources", workflows=await nav())

    @app.get("/api/resources")
    async def list_resources(email: str = Depends(auth.require_owner)):
        return await state.resource_store.list()

    @app.get("/api/resources/settings")
    async def get_resource_settings(email: str = Depends(auth.require_owner)):
        return {"write_mode": await state.resource_writes.get_mode()}

    @app.put("/api/resources/settings")
    async def put_resource_settings(body: WriteModeRequest,
                                    email: str = Depends(auth.require_owner)):
        try:
            return {"write_mode":
                    await state.resource_writes.set_mode(body.write_mode)}
        except ResourceError as e:
            raise StarletteHTTPException(400, str(e)) from None

    @app.get("/api/resources/pending")
    async def list_pending_edits(email: str = Depends(auth.require_owner)):
        return await state.resource_writes.list_pending()

    @app.post("/api/resources/pending/{pending_id}/approve")
    async def approve_pending_edit(pending_id: str,
                                   email: str = Depends(auth.require_owner)):
        try:
            ok = await state.resource_writes.approve(pending_id)
        except ResourceError as e:
            raise StarletteHTTPException(400, str(e)) from None
        if not ok:
            raise StarletteHTTPException(404, "pending edit not found")
        return {"ok": True}

    @app.post("/api/resources/pending/{pending_id}/reject")
    async def reject_pending_edit(pending_id: str,
                                  email: str = Depends(auth.require_owner)):
        if not await state.resource_writes.reject(pending_id):
            raise StarletteHTTPException(404, "pending edit not found")
        return {"ok": True}

    @app.get("/api/resources/{name}")
    async def get_resource(name: str, email: str = Depends(auth.require_owner)):
        doc = await state.resource_store.get(name)
        if doc is None:
            raise StarletteHTTPException(404, "resource not found")
        return doc

    @app.put("/api/resources/{name}")
    async def put_resource(name: str, body: ResourcePutRequest,
                           email: str = Depends(auth.require_owner)):
        # The API is an owner-only write path; a PUT always lands as
        # source="user" — editing a seeded resource hands ownership to the
        # owner, and seed_dir stops touching it from then on.
        try:
            doc = await state.resource_store.save(
                name, body.kind, body.description, body.content, source="user")
        except ResourceError as e:
            raise StarletteHTTPException(400, str(e)) from None
        await state.resource_writes.reject_for_resource(name)
        return doc

    @app.delete("/api/resources/{name}")
    async def delete_resource(name: str, email: str = Depends(auth.require_owner)):
        if not await state.resource_store.delete(name):
            raise StarletteHTTPException(404, "resource not found")
        await state.resource_writes.reject_for_resource(name)
        return {"ok": True}

    # ---------- memories (spec §5.8) ----------

    @app.get("/memories", response_class=HTMLResponse)
    async def memories_page(email: str = Depends(auth.require_owner)):
        if spa_index():
            return spa_response()
        return jinja.get_template("memories.html").render(
            owner=email, active="memories", workflows=await nav())

    @app.get("/api/memories")
    async def list_memories(status: str | None = None, type: str | None = None,
                            email: str = Depends(auth.require_owner)):
        return await state.memory_store.list(status=status, type=type)

    @app.post("/api/memories")
    async def create_memory(body: MemoryCreateRequest,
                            email: str = Depends(auth.require_owner)):
        try:
            doc = await state.memory_store.save(
                text=body.text, type=body.type, importance=body.importance,
                source="owner")
        except MemoryError as e:
            raise StarletteHTTPException(400, str(e)) from None
        return {k: v for k, v in doc.items() if k != "embedding"}

    @app.put("/api/memories/{key}")
    async def update_memory(key: str, body: MemoryTextRequest,
                            email: str = Depends(auth.require_owner)):
        try:
            doc = await state.memory_store.update_text(key, body.text)
        except MemoryError as e:
            raise StarletteHTTPException(400, str(e)) from None
        if doc is None:
            raise StarletteHTTPException(404, "memory not found")
        return doc

    @app.post("/api/memories/{key}/archive")
    async def archive_memory(key: str, email: str = Depends(auth.require_owner)):
        doc = await state.memory_store.archive(key)
        if doc is None:
            raise StarletteHTTPException(404, "memory not found")
        return doc

    @app.post("/api/memories/{key}/restore")
    async def restore_memory(key: str, email: str = Depends(auth.require_owner)):
        doc = await state.memory_store.restore(key)
        if doc is None:
            raise StarletteHTTPException(404, "memory not found")
        return doc

    @app.delete("/api/memories/{key}")
    async def delete_memory(key: str, email: str = Depends(auth.require_owner)):
        if not await state.memory_store.delete(key):
            raise StarletteHTTPException(404, "memory not found")
        return {"ok": True}

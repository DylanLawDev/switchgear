from fastapi import Depends
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from switchgear import auth
from switchgear.approvals import APPROVAL_ERRORS


class ResolveApprovalRequest(BaseModel):
    action: str
    context: str | None = None


def register_approval_routes(app, state) -> None:
    @app.get("/api/approvals")
    async def list_approvals(email: str = Depends(auth.require_owner)):
        return await state.approvals.list()

    @app.get("/api/approvals/{kind}/{approval_id}")
    async def get_approval(kind: str, approval_id: str, context: str | None = None,
                           email: str = Depends(auth.require_owner)):
        approval = await state.approvals.get(kind, approval_id, context)
        if approval is None:
            raise StarletteHTTPException(404, "approval not found")
        return approval

    @app.post("/api/approvals/{kind}/{approval_id}")
    async def resolve_approval(kind: str, approval_id: str,
                               body: ResolveApprovalRequest,
                               email: str = Depends(auth.require_owner)):
        try:
            ok = await state.approvals.resolve(
                kind, approval_id, body.action, email, body.context)
        except APPROVAL_ERRORS as exc:
            raise StarletteHTTPException(400, str(exc)) from None
        if not ok:
            raise StarletteHTTPException(404, "pending approval not found")
        return {"ok": True}

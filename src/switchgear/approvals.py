import json
from datetime import datetime, timezone

from switchgear.resources.store import ResourceError
from switchgear.skills.agent_writes import SkillWriteError
from switchgear.definition_writes import DefinitionWriteError


class ApprovalRouter:
    def __init__(self, resource_writes, skill_writes, workflow_store, gated_actions,
                 definition_writes=None, chat_escalation_seconds: int = 900):
        self._resources = resource_writes
        self._skills = skill_writes
        self._workflows = workflow_store
        self._actions = gated_actions
        self._definitions = definition_writes
        self._chat_escalation_seconds = chat_escalation_seconds

    def _visible_in_inbox(self, doc: dict) -> bool:
        if doc.get("origin", "chat") != "chat":
            return True
        created = doc.get("created_at")
        if not created:
            return True
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(str(created).replace("Z", "+00:00"))).total_seconds()
        except ValueError:
            return True
        return age >= self._chat_escalation_seconds

    async def list(self) -> list[dict]:
        rows: list[dict] = []
        for doc in await self._resources.list_pending():
            if not self._visible_in_inbox(doc):
                continue
            rows.append({"kind": "resource_write", "id": doc["id"],
                         "status": "pending", "origin": doc.get("origin", "chat"),
                         "created_at": doc.get("created_at"),
                         "title": f"{doc['op']} resource {doc['resource_name']}"})
        for doc in await self._skills.list_pending():
            if not self._visible_in_inbox(doc):
                continue
            rows.append({"kind": "skill_write", "id": doc["id"],
                         "status": "pending", "origin": doc.get("origin", "chat"),
                         "created_at": doc.get("created_at"),
                         "title": f"{doc['op']} skill {doc['skill_name']}"})
        if self._definitions is not None:
            for doc in await self._definitions.list_pending():
                if not self._visible_in_inbox(doc):
                    continue
                rows.append({"kind": "definition_write", "id": doc["id"],
                             "status": "pending", "origin": doc.get("origin", "background"),
                             "created_at": doc.get("created_at"),
                             "title": f"{doc['op']} {doc['kind']} {doc['name']}"})
        for summary in await self._workflows.list():
            workflow = await self._workflows.get(summary["name"])
            if not workflow or not workflow.get("actions"):
                continue
            key_field = workflow["actions"]["key_field"]
            for doc in await self._actions.list(workflow):
                if doc.get("status") not in {"draft", "failed"}:
                    continue
                approval_id = doc.get(key_field) or doc.get("_id")
                rows.append({"kind": "workflow_action", "id": approval_id,
                             "context": workflow["name"], "status": "pending",
                             "origin": "background",
                             "created_at": doc.get("created_at"),
                             "title": f"approve {workflow['actions']['label']} "
                                      f"{approval_id}"})
        def created_epoch(row: dict) -> float:
            value = row.get("created_at")
            if isinstance(value, (int, float)):
                return float(value)
            try:
                return datetime.fromisoformat(
                    str(value).replace("Z", "+00:00")).timestamp()
            except (TypeError, ValueError):
                return 0.0

        rows.sort(key=created_epoch)
        return rows

    async def get(self, kind: str, approval_id: str,
                  context: str | None = None) -> dict | None:
        if kind == "resource_write":
            doc = await self._resources.get_proposal(approval_id)
            if doc is None:
                return None
            return {"kind": kind, "id": approval_id, "status": doc["status"],
                    "title": f"{doc['op']} resource {doc['resource_name']}",
                    "before": doc.get("old_content"), "after": doc.get("new_content")}
        if kind == "skill_write":
            doc = await self._skills.get_proposal(approval_id)
            if doc is None:
                return None
            return {"kind": kind, "id": approval_id, "status": doc["status"],
                    "title": f"{doc['op']} skill {doc['skill_name']}",
                    "before": doc.get("old_text"), "after": doc.get("text")}
        if kind == "definition_write" and self._definitions is not None:
            doc = await self._definitions.get(approval_id)
            if doc is None:
                return None
            return {"kind": kind, "id": approval_id, "status": doc["status"],
                    "title": f"{doc['op']} {doc['kind']} {doc['name']}",
                    "before": doc.get("old_text"), "after": doc.get("text"),
                    "origin": doc.get("origin", "background")}
        if kind == "workflow_action" and context:
            wf = await self._workflows.get(context)
            if wf is None or not wf.get("actions"):
                return None
            record = await self._actions.get(wf, approval_id)
            if record is None:
                return None
            status = "pending" if record.get("status") in ("draft", "failed") \
                else record.get("status")
            return {"kind": kind, "id": approval_id, "context": context,
                    "status": status,
                    "title": f"approve {wf['actions']['label']} {approval_id}",
                    "before": None,
                    "after": json.dumps(record.get("fields", []), indent=2)}
        return None

    async def resolve(self, kind: str, approval_id: str, action: str,
                      owner: str, context: str | None = None) -> bool:
        if action not in ("approve", "reject"):
            return False
        if kind == "resource_write":
            return await (self._resources.approve(approval_id) if action == "approve"
                          else self._resources.reject(approval_id))
        if kind == "skill_write":
            return await (self._skills.approve(approval_id) if action == "approve"
                          else self._skills.reject(approval_id))
        if kind == "definition_write" and self._definitions is not None:
            return await self._definitions.resolve(approval_id, action == "approve")
        if kind == "workflow_action" and context:
            wf = await self._workflows.get(context)
            if wf is None:
                return False
            result = await (self._actions.approve(wf, approval_id, approved_by=owner)
                            if action == "approve" else self._actions.reject(
                                wf, approval_id, comment="Rejected by owner in Chat"))
            return bool(result and not result.get("error"))
        return False


APPROVAL_ERRORS = (ResourceError, SkillWriteError, DefinitionWriteError)

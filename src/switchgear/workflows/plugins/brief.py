"""LlmBriefGenerator: item -> grounded markdown brief artifact.

Requires the workflow's artifacts kind to declare title/body/created_at
fields (the research workflow does)."""

import time
from uuid import uuid4

_SYSTEM = (
    "You are writing a concise research brief in markdown. Ground every claim "
    "in the source material given below; do not invent facts, numbers, or "
    "quotes. Use short headings and bullet lists. 250 words maximum. Reply "
    "with ONLY the markdown brief — no preamble, no code fences.")


class LlmBriefGenerator:
    def __init__(self, gateway, storage):
        self._gw = gateway
        self._db = storage

    async def generate(self, wf: dict, item: dict) -> dict:
        artifacts = wf.get("artifacts")
        if not artifacts:
            return {"error": "workflow has no artifacts kind"}
        items_kind = wf["items"]
        title = item.get(items_kind["title_field"]) or "untitled"
        source_lines = [f"{k}: {v}" for k, v in sorted(item.items())
                        if v is not None]
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",
             "content": "Source material:\n" + "\n".join(source_lines)},
        ]
        completion = await self._gw.complete("writing", messages)
        body = (completion.message.get("content") or "").strip()
        if not body:
            return {"error": "empty brief from model"}
        key = f"brief-{uuid4().hex[:12]}"
        record = {
            artifacts["key_field"]: key,
            artifacts["item_ref_field"]: item.get(items_kind["key_field"]),
            "title": f"Brief: {title}",
            "body": body,
            "created_at": time.time(),
        }
        await self._db.put(artifacts["collection"], key, record)
        return {"ok": True, "key": key, "usage": completion.usage}

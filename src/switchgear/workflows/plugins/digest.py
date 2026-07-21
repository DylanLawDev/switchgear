"""SendDigestExecutor: gated email send. Proves the action gate is not
browser-shaped. Constructed per workflow with the artifact collection it
reads — plugin instances may be workflow-specific; definitions still only
reference them by registered name."""

import html

from switchgear.workflows.actions import (
    DraftResult,
    ExecutionAmbiguous,
    ExecutionFailed,
)


class SendDigestExecutor:
    def __init__(self, storage, email_sender, settings, *,
                 artifacts_collection: str, item_ref_field: str):
        self._db = storage
        self._email = email_sender
        self._s = settings
        self._artifacts = artifacts_collection
        self._irf = item_ref_field

    async def draft(self, item: dict) -> DraftResult:
        briefs = await self._db.query(self._artifacts,
                                      where={self._irf: item.get("key")})
        briefs.sort(key=lambda b: b.get("created_at") or 0, reverse=True)
        body = "\n\n---\n\n".join(b.get("body") or "" for b in briefs)
        title = item.get("title") or "research"
        fields = [
            {"selector": "to", "label": "To", "value": self._s.owner_email,
             "source": "profile", "needs_you": False, "kind": "text"},
            {"selector": "subject", "label": "Subject",
             "value": f"Research digest — {title}", "source": "agent",
             "needs_you": False, "kind": "text"},
            {"selector": "body", "label": "Body (markdown)", "value": body,
             "source": "agent", "needs_you": not body, "kind": "multiline"},
        ]
        notes = "" if body else ("no briefs exist for this source yet — "
                                 "generate one first")
        return DraftResult(fields=fields, notes=notes,
                           extra={"item_title": title})

    async def execute(self, record: dict) -> dict:
        values = {f["selector"]: f.get("value") for f in record.get("fields", [])}
        to, subject, body = values.get("to"), values.get("subject"), values.get("body")
        if not to or not subject or not body:
            # No side effect attempted yet: safe to edit and re-approve.
            raise ExecutionFailed("digest needs to, subject, and body values")
        safe = html.escape(body)
        content = (f'<div style="white-space: pre-wrap; '
                   f'font-family: monospace">{safe}</div>')
        try:
            await self._email.send(to, subject, content)
        except Exception as e:
            # The send was in flight — a timeout may still have delivered.
            raise ExecutionAmbiguous(
                f"send may or may not have delivered: {type(e).__name__}: {e}"
            ) from e
        return {}

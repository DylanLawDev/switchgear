import time
from uuid import uuid4

from switchgear.config import Settings
from switchgear.email.sender import EmailSender
from switchgear.storage.base import Storage
from switchgear.tools.base import Tool


def make_send_email_tool(settings: Settings, sender: EmailSender, storage: Storage) -> Tool:
    async def _send(subject: str, html: str) -> dict:
        await sender.send(settings.owner_email, subject, html)
        await storage.put("audit", f"email-{uuid4().hex}",
                          {"tool": "send_email", "subject": subject, "at": time.time()})
        return {"ok": True}

    return Tool(
        name="send_email",
        description="Email the owner. Recipient is fixed to the owner's address.",
        parameters={"type": "object", "properties": {
            "subject": {"type": "string"}, "html": {"type": "string"}},
            "required": ["subject", "html"]},
        handler=_send,
    )

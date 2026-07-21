"""Provider-neutral channel transport interfaces and the local console transport."""

import logging
from abc import ABC, abstractmethod

from switchgear.config import Settings

logger = logging.getLogger(__name__)


class ChannelTransport(ABC):
    @abstractmethod
    async def fetch_new(self, cursor: str | None) -> tuple[list[dict], str | None]:
        """Return ``(messages, new_cursor)`` for newly available messages."""

    @abstractmethod
    async def send(self, to: str, subject: str, body_text: str,
                   in_reply_to: str | None = None) -> dict: ...


class ConsoleTransport(ChannelTransport):
    """In-memory transport for development and tests."""

    def __init__(self):
        self.inbox: list[dict] = []
        self.sent: list[dict] = []

    def append_inbound(self, msg: dict) -> None:
        self.inbox.append(msg)

    async def fetch_new(self, cursor: str | None) -> tuple[list[dict], str | None]:
        start = int(cursor) if cursor else 0
        return list(self.inbox[start:]), str(len(self.inbox))

    async def send(self, to: str, subject: str, body_text: str,
                   in_reply_to: str | None = None) -> dict:
        record = {"to": to, "subject": subject, "body_text": body_text,
                  "in_reply_to": in_reply_to}
        self.sent.append(record)
        logger.info("[channel] to=%s subject=%s\n%s", to, subject, body_text)
        return record


def get_transport(settings: Settings) -> ChannelTransport:
    return ConsoleTransport()

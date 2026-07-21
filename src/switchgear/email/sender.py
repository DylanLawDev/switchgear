import asyncio
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

from switchgear.config import Settings


def clean_header(value: str) -> str:
    return value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


class EmailSender(ABC):
    @abstractmethod
    async def send(self, to: str, subject: str, html: str) -> None: ...


class ConsoleEmailSender(EmailSender):
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, to: str, subject: str, html: str) -> None:
        # Sanitize headers to prevent injection
        to = clean_header(to)
        subject = clean_header(subject)
        self.sent.append({"to": to, "subject": subject, "html": html})
        print(f"[email] to={to} subject={subject}\n{html}")


class SMTPEmailSender(EmailSender):
    def __init__(self, settings: Settings):
        self._s = settings

    async def send(self, to: str, subject: str, html: str) -> None:
        message = EmailMessage()
        message["From"] = clean_header(self._s.smtp_from)
        message["To"] = clean_header(to)
        message["Subject"] = clean_header(subject)
        message.set_content("This message requires an HTML-capable email client.")
        message.add_alternative(html, subtype="html")

        def _send():
            with smtplib.SMTP(self._s.smtp_host, self._s.smtp_port, timeout=30) as smtp:
                if self._s.smtp_starttls:
                    smtp.starttls()
                if self._s.smtp_username:
                    smtp.login(self._s.smtp_username, self._s.smtp_password)
                smtp.send_message(message)

        await asyncio.to_thread(_send)

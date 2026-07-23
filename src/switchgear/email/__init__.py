from switchgear.config import Settings
from switchgear.email.sender import (
    ConsoleEmailSender,
    DynamicEmailSender,
    EmailSender,
    SMTPEmailSender,
)


def get_email_sender(settings: Settings) -> EmailSender:
    return DynamicEmailSender(settings)

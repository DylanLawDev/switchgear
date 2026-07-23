from switchgear.config import Settings
from switchgear.email.sender import (
    ConsoleEmailSender as ConsoleEmailSender,
    DynamicEmailSender as DynamicEmailSender,
    EmailSender as EmailSender,
    SMTPEmailSender as SMTPEmailSender,
)


def get_email_sender(settings: Settings) -> EmailSender:
    return DynamicEmailSender(settings)

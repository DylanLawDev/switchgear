from switchgear.config import Settings
from switchgear.email.sender import ConsoleEmailSender, EmailSender, SMTPEmailSender


def get_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend == "smtp":
        return SMTPEmailSender(settings)
    return ConsoleEmailSender()

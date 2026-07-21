from switchgear.config import Settings
from switchgear.email.sender import SMTPEmailSender


async def test_smtp_sender_uses_tls_login_and_sanitized_headers(monkeypatch):
    events = []

    class SMTP:
        def __init__(self, host, port, timeout):
            events.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self):
            events.append(("tls",))

        def login(self, username, password):
            events.append(("login", username, password))

        def send_message(self, message):
            events.append(("send", message["To"], message["Subject"]))

    monkeypatch.setattr("switchgear.email.sender.smtplib.SMTP", SMTP)
    settings = Settings(
        _env_file=None, smtp_host="smtp.example.com", smtp_port=587,
        smtp_username="owner", smtp_password="secret",
        smtp_from="agent@example.com",
    )
    await SMTPEmailSender(settings).send(
        "owner@example.com\nBcc: attacker@example.com", "Report\r\nBcc: no", "<b>ok</b>"
    )
    assert events == [
        ("connect", "smtp.example.com", 587, 30),
        ("tls",),
        ("login", "owner", "secret"),
        ("send", "owner@example.com", "Report Bcc: no"),
    ]

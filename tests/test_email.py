from switchgear.config import Settings
from switchgear.email.sender import ConsoleEmailSender
from switchgear.storage.memory import MemoryStorage
from switchgear.tools.send_email import make_send_email_tool


async def test_send_email_goes_to_owner_only():
    s = Settings(_env_file=None, owner_email="me@example.com")
    sender = ConsoleEmailSender()
    storage = MemoryStorage()
    t = make_send_email_tool(s, sender, storage)
    assert "to" not in t.parameters["properties"]
    assert await t.handler(subject="Hi", html="<b>yo</b>") == {"ok": True}
    assert sender.sent == [{"to": "me@example.com", "subject": "Hi", "html": "<b>yo</b>"}]


async def test_send_email_writes_audit_record():
    s = Settings(_env_file=None, owner_email="me@example.com")
    sender = ConsoleEmailSender()
    storage = MemoryStorage()
    t = make_send_email_tool(s, sender, storage)
    await t.handler(subject="Hi", html="<b>yo</b>")
    audits = await storage.query("audit")
    assert len(audits) == 1
    assert audits[0]["tool"] == "send_email"
    assert audits[0]["subject"] == "Hi"
    assert isinstance(audits[0]["at"], float)


async def test_send_email_sanitizes_header_injection():
    sender = ConsoleEmailSender()
    # Test subject with CRLF injection attempt
    malicious_subject = "evil\r\nBcc: attacker@example.com"
    await sender.send("me@example.com", malicious_subject, "<b>test</b>")
    # \r\n collapses to a single space (as one unit), matching
    # channels/transport.py's _clean_header -- not doubled.
    assert sender.sent[0]["subject"] == "evil Bcc: attacker@example.com"
    # Verify no CRLF remains in stored subject
    assert "\r" not in sender.sent[0]["subject"]
    assert "\n" not in sender.sent[0]["subject"]


async def test_send_email_collapses_lone_cr_and_lf_too():
    sender = ConsoleEmailSender()
    await sender.send("me@example.com", "a\rb\nc\r\nd", "<b>test</b>")
    assert sender.sent[0]["subject"] == "a b c d"


async def test_dynamic_sender_switches_backend_at_runtime(monkeypatch):
    from switchgear.config import Settings
    from switchgear.email import get_email_sender
    from switchgear.email.sender import DynamicEmailSender

    settings = Settings(_env_file=None, email_backend="console")
    sender = get_email_sender(settings)
    assert isinstance(sender, DynamicEmailSender)
    await sender.send("a@b.c", "hi", "<p>x</p>")
    assert sender.sent[0]["to"] == "a@b.c"

    smtp_calls = []

    async def fake_smtp_send(to, subject, html):
        smtp_calls.append(to)

    monkeypatch.setattr(sender.smtp, "send", fake_smtp_send)
    settings.email_backend = "smtp"
    await sender.send("d@e.f", "yo", "<p>y</p>")
    assert smtp_calls == ["d@e.f"]
    assert len(sender.sent) == 1

from switchgear.channels.transport import ChannelTransport, ConsoleTransport, get_transport
from switchgear.config import Settings

S = Settings(_env_file=None, owner_email="owner@example.com", session_secret="s3")


async def test_console_fetch_all_then_only_new():
    transport = ConsoleTransport()
    transport.append_inbound({"provider_id": "m1"})
    transport.append_inbound({"provider_id": "m2"})
    messages, cursor = await transport.fetch_new(None)
    assert [message["provider_id"] for message in messages] == ["m1", "m2"]
    assert cursor == "2"
    messages, cursor = await transport.fetch_new(cursor)
    assert messages == [] and cursor == "2"
    transport.append_inbound({"provider_id": "m3"})
    messages, cursor = await transport.fetch_new("2")
    assert [message["provider_id"] for message in messages] == ["m3"]
    assert cursor == "3"


async def test_console_send_records_and_returns():
    transport = ConsoleTransport()
    result = await transport.send("a@example.com", "Hi", "hello", in_reply_to="<mid@x>")
    assert transport.sent == [{
        "to": "a@example.com", "subject": "Hi", "body_text": "hello",
        "in_reply_to": "<mid@x>",
    }]
    assert result == transport.sent[0]


def test_get_transport_returns_core_console_transport():
    transport = get_transport(S)
    assert isinstance(transport, ConsoleTransport)
    assert isinstance(transport, ChannelTransport)

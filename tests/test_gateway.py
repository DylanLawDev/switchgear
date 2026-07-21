import json

import httpx
import pytest
import respx

from switchgear.config import Settings
from switchgear.gateway import Gateway, GatewayError

S = Settings(_env_file=None, gateway_base_url="https://gw.test/v1", gateway_api_key="k",
             model_chat="m-chat")
URL = "https://gw.test/v1/chat/completions"


@respx.mock
async def test_complete_returns_message_and_usage():
    respx.post(URL).respond(json={
        "choices": [{"message": {"role": "assistant", "content": "hi"}}],
        "usage": {"total_tokens": 42},
    })
    c = await Gateway(S).complete("chat", [{"role": "user", "content": "hey"}])
    assert c.message["content"] == "hi" and c.usage == 42
    assert json.loads(respx.calls.last.request.content)["model"] == "m-chat"


@respx.mock
async def test_retry_then_success(monkeypatch):
    import switchgear.gateway as g

    async def no_sleep(_):
        pass

    monkeypatch.setattr(g.asyncio, "sleep", no_sleep)
    respx.post(URL).mock(side_effect=[
        httpx.Response(429),
        httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}],
                                  "usage": {"total_tokens": 1}}),
    ])
    assert (await Gateway(S).complete("chat", [])).message["content"] == "ok"


@respx.mock
async def test_retries_exhausted(monkeypatch):
    import switchgear.gateway as g

    async def no_sleep(_):
        pass

    monkeypatch.setattr(g.asyncio, "sleep", no_sleep)
    respx.post(URL).respond(500)
    with pytest.raises(GatewayError):
        await Gateway(S).complete("chat", [])


@respx.mock
async def test_stream_assembles_text_and_tool_calls():
    chunks = [
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1",
            "function": {"name": "ping", "arguments": "{\"a\""}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0,
            "function": {"arguments": ": 1}"}}]}}], "usage": {"total_tokens": 7}},
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    respx.post(URL).respond(200, content=body, headers={"content-type": "text/event-stream"})
    events = [e async for e in Gateway(S).stream("chat", [])]
    assert [e["delta"] for e in events if e["type"] == "text"] == ["Hel", "lo"]
    final = events[-1]
    assert final["type"] == "message" and final["usage"] == 7
    tc = final["message"]["tool_calls"][0]
    assert tc["function"]["name"] == "ping"
    assert json.loads(tc["function"]["arguments"]) == {"a": 1}


@respx.mock
async def test_stream_retry_then_success(monkeypatch):
    import switchgear.gateway as g

    async def no_sleep(_):
        pass

    monkeypatch.setattr(g.asyncio, "sleep", no_sleep)
    ok_body = ('data: {"choices": [{"delta": {"content": "hi"}}]}\n\n'
               'data: [DONE]\n\n')
    respx.post(URL).mock(side_effect=[
        httpx.Response(503),
        httpx.Response(200, content=ok_body,
                       headers={"content-type": "text/event-stream"}),
    ])
    events = [e async for e in Gateway(S).stream("chat", [])]
    assert events[0] == {"type": "text", "delta": "hi"}
    assert events[-1]["type"] == "message"


@respx.mock
async def test_stream_retries_exhausted(monkeypatch):
    import switchgear.gateway as g

    async def no_sleep(_):
        pass

    monkeypatch.setattr(g.asyncio, "sleep", no_sleep)
    respx.post(URL).respond(503)
    with pytest.raises(GatewayError):
        [e async for e in Gateway(S).stream("chat", [])]


@respx.mock
async def test_complete_401_raises_gateway_error():
    respx.post(URL).respond(401)
    with pytest.raises(GatewayError):
        await Gateway(S).complete("chat", [])


@respx.mock
async def test_stream_401_raises_gateway_error():
    respx.post(URL).respond(401)
    with pytest.raises(GatewayError):
        [e async for e in Gateway(S).stream("chat", [])]

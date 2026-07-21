import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from switchgear.config import Settings


class GatewayError(Exception):
    pass


@dataclass
class Completion:
    message: dict
    usage: int


RETRYABLE = {429, 500, 502, 503, 504}


class Gateway:
    def __init__(self, settings: Settings):
        self._s = settings

    def _req(self, tier: str, messages: list[dict], tools: list[dict] | None, stream: bool) -> dict:
        body: dict = {"model": self._s.model_for(tier), "messages": messages, "stream": stream}
        if tools:
            body["tools"] = tools
        if stream:
            body["stream_options"] = {"include_usage": True}
        return body

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._s.gateway_api_key}"}

    @property
    def _url(self) -> str:
        return f"{self._s.gateway_base_url}/chat/completions"

    async def complete(self, tier: str, messages: list[dict],
                       tools: list[dict] | None = None) -> Completion:
        for attempt in range(3):
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(self._url, json=self._req(tier, messages, tools, False),
                                         headers=self._headers)
            if resp.status_code in RETRYABLE:
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if resp.status_code >= 400:
                raise GatewayError(f"gateway error {resp.status_code}")
            data = resp.json()
            usage = (data.get("usage") or {}).get("total_tokens", 0)
            return Completion(message=data["choices"][0]["message"], usage=usage)
        raise GatewayError(f"gateway failed after retries: {resp.status_code}")

    async def stream(self, tier: str, messages: list[dict],
                     tools: list[dict] | None = None) -> AsyncIterator[dict]:
        for attempt in range(3):
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", self._url, headers=self._headers,
                                         json=self._req(tier, messages, tools, True)) as resp:
                    if resp.status_code in RETRYABLE:
                        await asyncio.sleep(0.5 * 2**attempt)
                        continue
                    if resp.status_code >= 400:
                        raise GatewayError(f"gateway error {resp.status_code}")
                    content_parts: list[str] = []
                    tool_calls: dict[int, dict] = {}
                    usage = 0
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload.strip() == "[DONE]":
                            break
                        chunk = json.loads(payload)
                        if chunk.get("usage"):
                            usage = chunk["usage"].get("total_tokens", usage)
                        choices = chunk.get("choices") or []
                        delta = choices[0].get("delta", {}) if choices else {}
                        if delta.get("content"):
                            content_parts.append(delta["content"])
                            yield {"type": "text", "delta": delta["content"]}
                        for tc in delta.get("tool_calls") or []:
                            slot = tool_calls.setdefault(tc["index"], {
                                "id": "", "type": "function",
                                "function": {"name": "", "arguments": ""}})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["function"]["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["function"]["arguments"] += fn["arguments"]
                    message: dict = {"role": "assistant",
                                     "content": "".join(content_parts) or None}
                    if tool_calls:
                        message["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]
                    yield {"type": "message", "message": message, "usage": usage}
                    return
        raise GatewayError("gateway stream failed after retries")

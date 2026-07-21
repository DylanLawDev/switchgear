import json
from typing import AsyncIterator

from switchgear.config import Settings
from switchgear.gateway import GatewayError
from switchgear.tools.base import ToolRegistry


class AgentLoop:
    def __init__(self, gateway, registry: ToolRegistry, settings: Settings):
        self._gw = gateway
        self._reg = registry
        self._s = settings

    async def run(self, messages: list[dict], tier: str = "chat",
                  allowlist: list[str] | None = None) -> AsyncIterator[dict]:
        transcript = list(messages)
        usage_total = 0
        tools = self._reg.schemas(allowlist) or None
        for _ in range(self._s.max_loop_iterations):
            final: dict | None = None
            async for event in self._gw.stream(tier, transcript, tools=tools):
                if event["type"] == "text":
                    yield event
                elif event["type"] == "message":
                    final = event
            if final is None:
                raise GatewayError("gateway stream ended without a message event")
            usage_total += final["usage"]
            assistant = final["message"]
            transcript.append(assistant)
            calls = assistant.get("tool_calls")
            if not calls:
                yield {"type": "done", "messages": transcript, "usage": usage_total}
                return
            if usage_total >= self._s.run_token_budget:
                yield {"type": "error", "reason": "token budget exceeded", "messages": transcript}
                return
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    result = json.dumps({"error": "invalid tool arguments"})
                else:
                    yield {"type": "tool_call", "name": name, "args": args}
                    result = await self._reg.execute(name, args, allowlist=allowlist)
                yield {"type": "tool_result", "name": name, "result": result}
                transcript.append({"role": "tool", "tool_call_id": call["id"],
                                   "content": result})
        yield {"type": "error", "reason": "iteration limit reached", "messages": transcript}

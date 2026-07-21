from switchgear.gateway import Gateway
from switchgear.tools.base import Tool


def make_llm_tool(gateway: Gateway) -> Tool:
    async def _llm(tier: str, prompt: str, system: str | None = None) -> dict:
        messages = ([{"role": "system", "content": system}] if system else [])
        messages.append({"role": "user", "content": prompt})
        c = await gateway.complete(tier, messages)
        return {"text": c.message.get("content"), "usage": c.usage}

    return Tool(
        name="llm",
        description="Run a one-shot LLM completion on a model tier (chat/bulk/writing) "
                    "without polluting the conversation context. Use bulk for cheap batch work.",
        parameters={"type": "object", "properties": {
            "tier": {"type": "string", "enum": ["chat", "bulk", "writing"]},
            "prompt": {"type": "string"},
            "system": {"type": "string"}},
            "required": ["tier", "prompt"]},
        handler=_llm,
    )

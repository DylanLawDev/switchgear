import json
from dataclasses import dataclass


@dataclass
class FakeCompletion:
    """Mirrors switchgear.gateway.Completion (.message / .usage)."""

    message: dict
    usage: int = 1


_EMPTY_REFLECTION = json.dumps({"memories": []})


class FakeGateway:
    def __init__(self, scripts, completions=None):
        self._scripts = list(scripts)
        self._completions = list(completions or [])
        self.calls: list[dict] = []
        self.complete_calls: list[dict] = []

    async def stream(self, tier, messages, tools=None):
        self.calls.append({"tier": tier, "messages": list(messages), "tools": tools})
        for event in self._scripts.pop(0):
            yield event

    async def complete(self, tier, messages, tools=None):
        self.complete_calls.append({"tier": tier, "messages": list(messages),
                                    "tools": tools})
        if not self._completions:
            # Unscripted complete() calls (e.g. background reflection in chat tests
            # that don't care about it) get a harmless empty proposal set.
            return FakeCompletion(
                message={"role": "assistant", "content": _EMPTY_REFLECTION})
        item = self._completions.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            return FakeCompletion(message={"role": "assistant", "content": item})
        return item

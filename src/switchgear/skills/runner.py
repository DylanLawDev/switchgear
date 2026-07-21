import logging
import time
from uuid import uuid4

from switchgear.loop import AgentLoop

logger = logging.getLogger(__name__)


def runner_prompt(owner_email: str, skill: dict, core_memories: str = "") -> str:
    standing = (f"\n## Standing instructions (memories)\n{core_memories}\n"
                if core_memories else "")
    return (
        f"You are switchgear, executing a skill for {owner_email}.\n"
        f"Skill: {skill['name']} — {skill['description']}\n"
        "Follow this playbook exactly, using only the tools available to you. "
        "When you are finished, briefly state the outcome.\n"
        f"{standing}\n"
        f"{skill['body']}"
    )


class SkillRunner:
    def __init__(self, gateway, registry, store, settings, storage, email_sender=None,
                 memory_store=None):
        self._gw = gateway
        self._reg = registry
        self._store = store
        self._s = settings
        self._db = storage
        self._email = email_sender
        self._memory = memory_store

    async def run(self, name: str, trigger: str = "manual") -> dict:
        skill = await self._store.get(name)
        if skill is None:
            return {"ok": False, "error": "skill not found"}
        if skill["status"] != "active":
            return {"ok": False, "error": "skill not active"}

        core = ""
        if self._memory is not None:
            try:
                core = await self._memory.core_block()
            except Exception:
                # Standing instructions must never break a skill run.
                logger.warning("core memory block unavailable for skill run '%s'",
                               name, exc_info=True)

        messages = [
            {"role": "system",
             "content": runner_prompt(self._s.owner_email, skill, core_memories=core)},
            {"role": "user", "content": f"Execute the '{name}' skill now."},
        ]
        loop = AgentLoop(self._gw, self._reg, self._s)
        tool_calls: list[str] = []
        text, usage, ok, error = "", 0, True, None
        try:
            async for ev in loop.run(messages, allowlist=skill["tools"]):
                if ev["type"] == "tool_call":
                    tool_calls.append(ev["name"])
                elif ev["type"] == "text":
                    text += ev["delta"]
                elif ev["type"] == "done":
                    usage = ev["usage"]
                elif ev["type"] == "error":
                    ok, error = False, ev.get("reason", "run error")
        except Exception as e:  # a gateway/loop failure must still produce a record
            ok, error = False, f"{type(e).__name__}: {e}"

        await self._db.put("runs", f"run-{uuid4().hex}", {
            "skill": name, "trigger": trigger, "at": time.time(), "ok": ok,
            "usage": usage, "error": error, "tool_calls": tool_calls,
            "summary": text[:500]})

        if not ok and self._email is not None:
            await self._email.send(
                self._s.owner_email, f"Skill '{name}' run failed",
                f"<p>Trigger: {trigger}</p><p>Error: {error}</p>")

        return {"ok": ok, "skill": name, "usage": usage, "error": error,
                "tool_calls": tool_calls}

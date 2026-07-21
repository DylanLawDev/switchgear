import json
import time
from uuid import uuid4

from jsonschema import Draft202012Validator

from switchgear.agents.store import AgentProfileStore
from switchgear.loop import AgentLoop
from switchgear.tools.base import use_origin, use_policy


class AgentRunError(Exception):
    pass


class AgentRunner:
    """One implementation shared by workflow, helper, and delegated agents."""

    def __init__(self, gateway, registry, profiles, skills, storage, settings):
        self._gateway = gateway
        self._registry = registry
        self._profiles = profiles
        self._skills = skills
        self._db = storage
        self._settings = settings

    async def run(self, task: str, *, profile_name: str = "",
                  skills: list[str] | None = None, context: object = None,
                  output_schema: dict | None = None, origin: str = "subagent",
                  instructions: str | None = None) -> dict:
        profile = await self._profiles.get(profile_name) if profile_name else None
        if profile_name and (profile is None or profile.get("status") != "active"):
            return {"ok": False, "error": f"agent profile not active: {profile_name}"}
        policy = AgentProfileStore.policy(profile)
        selected_skills = list(skills or [])
        if profile and profile.get("skills") is not None:
            selected_skills = list(dict.fromkeys([*profile["skills"], *selected_skills]))
        skill_blocks = []
        for name in selected_skills:
            if not policy.allows_skill(name):
                return {"ok": False, "error": f"skill access denied: {name}"}
            skill = await self._skills.get(name)
            if skill is None or skill.get("status") != "active":
                return {"ok": False, "error": f"skill not active: {name}"}
            skill_blocks.append(f"## Skill: {name}\n{skill['body']}")
        schema = output_schema or (profile or {}).get("output_schema")
        system = instructions or (profile or {}).get("prompt") \
            or "You are a focused subagent. Complete the task."
        if skill_blocks:
            system += "\n\n" + "\n\n".join(skill_blocks)
        if schema:
            system += ("\n\nReturn only JSON matching this schema. Do not use a code fence:\n" +
                       json.dumps(schema, sort_keys=True))
        user = task
        if context is not None:
            user += "\n\nContext:\n" + (context if isinstance(context, str)
                                              else json.dumps(context, sort_keys=True))
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        output, usage, calls, error = None, 0, [], None
        attempts = 0
        with use_origin(origin), use_policy(policy):
            while attempts < 3:
                attempts += 1
                text = ""
                loop = AgentLoop(self._gateway, self._registry, self._settings)
                async for event in loop.run(messages, tier=(profile or {}).get(
                        "model_tier", "chat")):
                    if event["type"] == "text":
                        text += event["delta"]
                    elif event["type"] == "tool_call":
                        calls.append(event["name"])
                    elif event["type"] == "done":
                        usage += event["usage"]
                        messages = event["messages"]
                    elif event["type"] == "error":
                        error = event.get("reason", "agent run failed")
                if error:
                    break
                if not schema:
                    output = text
                    break
                try:
                    candidate = json.loads(text)
                    errors = list(Draft202012Validator(schema).iter_errors(candidate))
                    if errors:
                        raise ValueError("; ".join(e.message for e in errors[:5]))
                    output = candidate
                    break
                except (json.JSONDecodeError, ValueError) as exc:
                    messages.append({"role": "user", "content":
                                     f"Your output failed schema validation: {exc}. "
                                     "Return corrected JSON only."})
        if output is None and error is None:
            error = "structured output failed validation after 3 attempts"
        run_id = f"agent-{uuid4().hex}"
        record = {"id": run_id, "origin": origin, "profile": profile_name or None,
                  "task": task, "ok": output is not None, "output": output,
                  "error": error, "usage": usage, "tool_calls": calls,
                  "attempts": attempts, "at": time.time(), "messages": messages}
        await self._db.put("agent-runs", run_id, record)
        return {k: record[k] for k in
                ("id", "ok", "output", "error", "usage", "tool_calls", "attempts")}

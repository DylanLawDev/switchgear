from switchgear.skills.model import SkillParseError
from switchgear.tools.base import Tool

_READ_FIELDS = ("name", "description", "tools", "schedule", "body", "status", "source")


def make_read_skill_tool(store) -> Tool:
    async def _read(name: str) -> dict:
        doc = await store.get(name)
        if doc is None:
            return {"error": f"skill not found: {name}"}
        return {k: doc[k] for k in _READ_FIELDS if k in doc}

    return Tool(
        name="read_skill",
        description="Read a skill's full playbook and metadata by name.",
        parameters={"type": "object", "properties": {"name": {"type": "string"}},
                    "required": ["name"]},
        handler=_read,
    )


def make_write_skill_tool(writes) -> Tool:
    async def _write(text: str) -> dict:
        try:
            return await writes.propose(text)
        except SkillParseError as e:
            return {"error": f"skill parse failed: {e}"}

    return Tool(
        name="write_skill",
        description=("Create or edit a skill (YAML frontmatter with name/description/tools/"
                     "optional schedule, then a numbered playbook). The write is queued and "
                     "does not change the active skill until the owner approves it in Chat."),
        parameters={"type": "object", "properties": {"text": {"type": "string"}},
                    "required": ["text"]},
        handler=_write,
    )

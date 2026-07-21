import re

import yaml

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


class SkillParseError(Exception):
    pass


def parse_skill(text: str) -> dict:
    if not text.startswith("---"):
        raise SkillParseError("missing frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SkillParseError("unterminated frontmatter")
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        raise SkillParseError(f"bad yaml: {e}") from None
    if not isinstance(meta, dict):
        raise SkillParseError("frontmatter must be a mapping")
    name, description = meta.get("name"), meta.get("description")
    if not name or not description:
        raise SkillParseError("name and description are required")
    if not NAME_RE.match(str(name)):
        raise SkillParseError("invalid name (lowercase alphanumerics and dashes)")
    tools = meta.get("tools") or []
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        raise SkillParseError("tools must be a list of strings")
    schedule = meta.get("schedule")
    return {
        "name": str(name),
        "description": str(description),
        "tools": tools,
        "schedule": str(schedule) if schedule else None,
        "body": parts[2].lstrip("\n"),
    }


def render_skill(doc: dict) -> str:
    meta: dict = {
        "name": doc["name"],
        "description": doc["description"],
        "tools": doc["tools"],
    }
    if doc.get("schedule"):
        meta["schedule"] = doc["schedule"]
    front = yaml.safe_dump(meta, default_flow_style=None, sort_keys=False).strip()
    return f"---\n{front}\n---\n{doc['body']}"

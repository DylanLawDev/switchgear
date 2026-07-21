import re

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
TIERS = {"chat", "bulk", "writing"}


class AgentProfileError(Exception):
    pass


def _optional_strings(meta: dict, key: str) -> list[str] | None:
    if key not in meta:
        return None
    value = meta[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AgentProfileError(f"{key} must be a list of strings")
    return value


def parse_agent_profile(text: str) -> dict:
    if not text.startswith("---"):
        raise AgentProfileError("missing frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise AgentProfileError("unterminated frontmatter")
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise AgentProfileError(f"bad yaml: {exc}") from None
    if not isinstance(meta, dict):
        raise AgentProfileError("frontmatter must be a mapping")
    if meta.get("schema_version", 1) != 1:
        raise AgentProfileError("schema_version must be 1")
    name = str(meta.get("name") or "")
    description = str(meta.get("description") or "")
    tier = str(meta.get("model_tier") or "chat")
    if not NAME_RE.fullmatch(name):
        raise AgentProfileError("invalid name")
    if not description:
        raise AgentProfileError("description is required")
    if tier not in TIERS:
        raise AgentProfileError("model_tier must be chat, bulk, or writing")
    output_schema = meta.get("output_schema")
    if output_schema is not None:
        if not isinstance(output_schema, dict):
            raise AgentProfileError("output_schema must be a mapping")
        try:
            Draft202012Validator.check_schema(output_schema)
        except SchemaError as exc:
            raise AgentProfileError(f"invalid output_schema: {exc.message}") from None
    return {
        "schema_version": 1,
        "name": name,
        "description": description,
        "model_tier": tier,
        "tools": _optional_strings(meta, "tools"),
        "resources": _optional_strings(meta, "resources"),
        "skills": _optional_strings(meta, "skills"),
        "output_schema": output_schema,
        "prompt": parts[2].lstrip("\n"),
    }

"""Parse and validate manifest-driven data apps and executable workflows."""

import re

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
DURATION_RE = re.compile(r"^(\d+)([mhd])$")
_DURATION_SECONDS = {"m": 60, "h": 3600, "d": 86400}

FIELD_TYPES = {"text", "markdown", "number", "score", "boolean", "enum", "status",
               "timestamp", "url", "image", "artifact", "relation", "json"}

DEFAULT_APPROVAL_TTL = "7d"
DEFAULT_DRAFT_TTL = "30d"


class WorkflowParseError(Exception):
    pass


def parse_duration(value: str) -> float:
    m = DURATION_RE.match(str(value))
    if not m:
        raise WorkflowParseError(f"bad duration: {value!r} (use e.g. 90m, 6h, 2d)")
    return float(m.group(1)) * _DURATION_SECONDS[m.group(2)]


def _parse_fields(kind_name: str, raw: object) -> dict:
    if not isinstance(raw, dict) or not raw:
        raise WorkflowParseError(f"{kind_name}.fields must be a non-empty mapping")
    fields = {}
    for fname, spec in raw.items():
        if not isinstance(spec, dict) or "type" not in spec:
            raise WorkflowParseError(f"{kind_name}.fields.{fname} needs a type")
        if spec["type"] not in FIELD_TYPES:
            raise WorkflowParseError(
                f"{kind_name}.fields.{fname}: unknown type {spec['type']!r}")
        fields[str(fname)] = {**spec, "type": str(spec["type"])}
    return fields


def _check_subset(kind_name: str, key: str, names: list, declared: dict) -> list:
    for n in names:
        bare = n.lstrip("-") if key == "sort" else n
        if bare not in declared:
            raise WorkflowParseError(f"{kind_name}.{key}: {bare!r} is not a declared field")
    return [str(n) for n in names]


def _parse_kind(wf_name: str, kind_name: str, raw: dict, *, with_ref: bool) -> dict:
    if not isinstance(raw, dict):
        raise WorkflowParseError(f"{kind_name} must be a mapping")
    for req in ("label", "label_plural", "title_field"):
        if not raw.get(req):
            raise WorkflowParseError(f"{kind_name}.{req} is required")
    fields = _parse_fields(kind_name, raw.get("fields"))
    if raw["title_field"] not in fields:
        raise WorkflowParseError(f"{kind_name}.title_field is not a declared field")
    list_fields = raw.get("list_fields") or list(fields)
    detail_fields = raw.get("detail_fields")
    sort = raw.get("sort") or ["-created_at"]
    sortable = {"number", "score", "timestamp"}
    checked_sort = (_check_subset(kind_name, "sort", sort, fields)
                    if sort != ["-created_at"] else sort)
    for spec in checked_sort:
        bare = spec.lstrip("-")
        if bare in fields and fields[bare]["type"] not in sortable:
            raise WorkflowParseError(
                f"{kind_name}.sort: {bare!r} is not a sortable type (number/score/timestamp)")
    kind = {
        "label": str(raw["label"]),
        "label_plural": str(raw["label_plural"]),
        "collection": str(raw.get("collection") or f"wf-{wf_name}-{kind_name}"),
        "key_field": str(raw.get("key_field") or "key"),
        "title_field": str(raw["title_field"]),
        "fields": fields,
        "list_fields": _check_subset(kind_name, "list_fields", list_fields, fields),
        "detail_fields": (_check_subset(kind_name, "detail_fields", detail_fields, fields)
                          if detail_fields else None),
        "sort": checked_sort,
        "expected_update_period": (parse_duration(raw["expected_update_period"])
                                   if raw.get("expected_update_period") else None),
        "retention": parse_duration(raw["retention"]) if raw.get("retention") else None,
    }
    if with_ref:
        kind["item_ref_field"] = str(raw.get("item_ref_field") or "item_key")
    return kind


def _parse_actions(wf_name: str, raw: dict, executors: set[str]) -> dict:
    if not isinstance(raw, dict):
        raise WorkflowParseError("actions must be a mapping")
    for req in ("label", "label_plural", "executor"):
        if not raw.get(req):
            raise WorkflowParseError(f"actions.{req} is required")
    if raw["executor"] not in executors:
        raise WorkflowParseError(f"actions.executor {raw['executor']!r} is not registered")
    return {
        "label": str(raw["label"]),
        "label_plural": str(raw["label_plural"]),
        "collection": str(raw.get("collection") or f"wf-{wf_name}-actions"),
        "key_field": str(raw.get("key_field") or "key"),
        "item_ref_field": str(raw.get("item_ref_field") or "item_key"),
        "executor": str(raw["executor"]),
        "approval_ttl": parse_duration(raw.get("approval_ttl") or DEFAULT_APPROVAL_TTL),
        "draft_ttl": parse_duration(raw.get("draft_ttl") or DEFAULT_DRAFT_TTL),
    }


def _schema(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        raise WorkflowParseError(f"{path} must be a JSON Schema mapping")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise WorkflowParseError(f"{path}: {exc.message}") from None
    return value


def _compile_cel(expression: str, path: str) -> None:
    try:
        from cel_expr_python import cel

        env = cel.NewEnv(variables={name: cel.Type.DYN for name in
                                    ("inputs", "steps", "refs", "run")})
        env.compile(expression)
    except Exception as exc:
        raise WorkflowParseError(f"{path}: invalid CEL: {exc}") from None


def _parse_execution(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise WorkflowParseError("execution must be a mapping")
    inputs = _schema(raw.get("inputs") or {"type": "object"}, "execution.inputs")
    outputs = _schema(raw.get("outputs") or {}, "execution.outputs")
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise WorkflowParseError("execution.steps must be a non-empty list")
    parsed, seen = [], set()
    for index, step in enumerate(steps):
        path = f"execution.steps[{index}]"
        if not isinstance(step, dict):
            raise WorkflowParseError(f"{path} must be a mapping")
        step_id = str(step.get("id") or "")
        step_type = str(step.get("type") or "")
        if not NAME_RE.fullmatch(step_id) or step_id in seen:
            raise WorkflowParseError(f"{path}.id must be unique and name-like")
        if step_type not in {"agent", "tool", "transform"}:
            raise WorkflowParseError(f"{path}.type must be agent, tool, or transform")
        seen.add(step_id)
        out = {"id": step_id, "type": step_type}
        if step.get("when") is not None:
            out["when"] = str(step["when"])
            _compile_cel(out["when"], f"{path}.when")
        if step.get("output_schema") is not None:
            out["output_schema"] = _schema(step["output_schema"], f"{path}.output_schema")
        if step_type == "agent":
            if not step.get("prompt"):
                raise WorkflowParseError(f"{path}.prompt is required")
            skills = step.get("skills") or []
            if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
                raise WorkflowParseError(f"{path}.skills must be a list of strings")
            out.update({"agent": str(step.get("agent") or ""),
                        "skills": skills, "prompt": str(step["prompt"])})
            if step.get("context") is not None:
                out["context"] = str(step["context"])
                _compile_cel(out["context"], f"{path}.context")
        elif step_type == "tool":
            if not step.get("tool"):
                raise WorkflowParseError(f"{path}.tool is required")
            out["tool"] = str(step["tool"])
            args = step.get("args", {})
            if not isinstance(args, (dict, str)):
                raise WorkflowParseError(f"{path}.args must be a mapping or CEL expression")
            out["args"] = args
            if isinstance(args, str):
                _compile_cel(args, f"{path}.args")
        else:
            if not step.get("expression"):
                raise WorkflowParseError(f"{path}.expression is required")
            out["expression"] = str(step["expression"])
            _compile_cel(out["expression"], f"{path}.expression")
        parsed.append(out)
    output = raw.get("output")
    if output is not None:
        _compile_cel(str(output), "execution.output")
    return {"inputs": inputs, "outputs": outputs, "steps": parsed,
            "output": str(output) if output is not None else None}


def parse_workflow(text: str, *, generators: set[str], executors: set[str]) -> dict:
    if not text.startswith("---"):
        raise WorkflowParseError("missing frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise WorkflowParseError("unterminated frontmatter")
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        raise WorkflowParseError(f"bad yaml: {e}") from None
    if not isinstance(meta, dict):
        raise WorkflowParseError("frontmatter must be a mapping")

    version = meta.get("schema_version")
    if version not in (1, 2):
        raise WorkflowParseError("schema_version must be 1 or 2")
    name, description = meta.get("name"), meta.get("description")
    if not name or not description:
        raise WorkflowParseError("name and description are required")
    if not NAME_RE.match(str(name)):
        raise WorkflowParseError("invalid name (lowercase alphanumerics and dashes)")
    name = str(name)

    ui_home = str(meta.get("ui_home") or "workflows")
    if ui_home not in ("workflows", "channels"):
        raise WorkflowParseError("ui_home must be 'workflows' or 'channels'")

    if version == 1 and "items" not in meta:
        raise WorkflowParseError("items kind is required")
    items = (_parse_kind(name, "items", meta["items"], with_ref=False)
             if meta.get("items") else None)
    artifacts = (_parse_kind(name, "artifacts", meta["artifacts"], with_ref=True)
                 if meta.get("artifacts") else None)
    actions = (_parse_actions(name, meta["actions"], executors)
               if meta.get("actions") else None)

    intake = meta.get("intake") or {}
    skills = intake.get("skills") or []
    if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
        raise WorkflowParseError("intake.skills must be a list of strings")

    generate = None
    if meta.get("generate"):
        g = meta["generate"]
        if not isinstance(g, dict) or not g.get("plugin"):
            raise WorkflowParseError("generate.plugin is required")
        if g["plugin"] not in generators:
            raise WorkflowParseError(f"generate.plugin {g['plugin']!r} is not registered")
        generate = {"plugin": str(g["plugin"]), "label": str(g.get("label") or "Generate")}

    execution = _parse_execution(meta["execution"]) if meta.get("execution") else None
    if version == 2 and items is None and execution is None:
        raise WorkflowParseError("schema v2 needs items or execution")

    return {
        "schema_version": version, "name": name, "description": str(description),
        "ui_home": ui_home,
        "items": items, "artifacts": artifacts, "actions": actions,
        "intake": {"skills": [str(s) for s in skills]}, "generate": generate,
        "execution": execution, "body": parts[2].lstrip("\n"),
    }

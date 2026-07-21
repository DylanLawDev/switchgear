"""Typed @reference catalog used by prompts, forms, and workflow inputs."""

import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Any

from switchgear.tools.base import current_policy

REFERENCE_RE = re.compile(r"(?<![\w@])@((?:\\.|[^\s,@])+)")


class ReferenceError(Exception):
    pass


def split_reference(value: str) -> list[str]:
    raw = value[1:] if value.startswith("@") else value
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in raw:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ".":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    parts.append("".join(current))
    if any(not part for part in parts):
        raise ReferenceError("reference path contains an empty segment")
    return parts


def join_reference(parts: list[str]) -> str:
    def escape(part: str) -> str:
        return "".join("\\" + c if c in ". @\\" else c for c in part)
    return "@" + ".".join(escape(part) for part in parts)


@dataclass
class Suggestion:
    path: str
    label: str
    type: str
    description: str = ""
    has_children: bool = False

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class ReferenceService:
    def __init__(self, resource_store, workflow_store):
        self._resources = resource_store
        self._workflows = workflow_store

    def _authorize(self, parts: list[str]) -> None:
        path = "/".join(parts[:2])
        if not current_policy.get().allows_resource(path):
            raise ReferenceError(f"reference access denied: {join_reference(parts[:2])}")

    async def suggest(self, parent: str = "", query: str = "") -> list[dict]:
        parts = split_reference(parent) if parent else []
        needle = query.lower()
        if not parts:
            rows = [
                Suggestion("@resources", "resources", "namespace",
                           "Owner-curated JSON, CSV, Markdown, and text", True),
                Suggestion("@workflows", "workflows", "namespace",
                           "Registered workflow identities", True),
            ]
        elif parts == ["resources"]:
            rows = [Suggestion(join_reference(["resources", r["name"]]), r["name"],
                               f"resource:{r['kind']}", r.get("description", ""), True)
                    for r in await self._resources.list()
                    if current_policy.get().allows_resource(f"resources/{r['name']}")]
        elif parts == ["workflows"]:
            rows = [Suggestion(join_reference(["workflows", w["name"]]), w["name"],
                               "workflow_ref", w.get("description", ""), False)
                    for w in await self._workflows.list()
                    if current_policy.get().allows_resource(f"workflows/{w['name']}")]
        elif parts[0] == "resources" and len(parts) >= 2:
            self._authorize(parts)
            value = await self.resolve(join_reference(parts))
            rows = self._children(parts, value)
        else:
            rows = []
        return [row.as_dict() for row in rows if not needle or needle in row.label.lower()]

    def _children(self, parts: list[str], value: Any) -> list[Suggestion]:
        if isinstance(value, dict):
            return [Suggestion(join_reference([*parts, str(key)]), str(key),
                               self._type(child), has_children=isinstance(child, (dict, list)))
                    for key, child in value.items()]
        if isinstance(value, list):
            return [Suggestion(join_reference([*parts, str(i)]), str(i),
                               self._type(child), has_children=isinstance(child, (dict, list)))
                    for i, child in enumerate(value[:100])]
        return []

    @staticmethod
    def _type(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "string"

    async def resolve(self, reference: str) -> Any:
        parts = split_reference(reference)
        if len(parts) < 2 or parts[0] not in {"resources", "workflows"}:
            raise ReferenceError(f"unknown reference: {reference}")
        self._authorize(parts)
        if parts[0] == "workflows":
            if len(parts) != 2:
                raise ReferenceError("workflow references do not have value children")
            workflow = await self._workflows.get(parts[1])
            if workflow is None or workflow.get("status") != "active":
                raise ReferenceError(f"unknown active workflow: {parts[1]}")
            return {"type": "workflow_ref", "name": parts[1]}
        resource = await self._resources.get(parts[1])
        if resource is None:
            raise ReferenceError(f"unknown resource: {parts[1]}")
        kind = resource["kind"]
        if kind == "json":
            value: Any = json.loads(resource["content"])
        elif kind == "csv":
            rows = list(csv.DictReader(io.StringIO(resource["content"])))
            columns = {field: [row.get(field) for row in rows]
                       for field in (rows[0].keys() if rows else [])}
            value = {"rows": rows, "columns": columns,
                     "meta": self._metadata(resource)}
        else:
            value = {"content": resource["content"], "meta": self._metadata(resource)}
        if kind == "json" and len(parts) == 2:
            return value
        for segment in parts[2:]:
            if isinstance(value, dict) and segment in value:
                value = value[segment]
            elif isinstance(value, list) and segment.isdigit() and int(segment) < len(value):
                value = value[int(segment)]
            else:
                raise ReferenceError(f"path not found: {reference}")
        return value

    @staticmethod
    def _metadata(resource: dict) -> dict:
        return {key: resource.get(key) for key in
                ("name", "kind", "description", "size", "updated_at")}

    async def interpolate(self, text: str) -> tuple[str, dict[str, Any]]:
        snapshot: dict[str, Any] = {}
        output: list[str] = []
        cursor = 0
        for match in REFERENCE_RE.finditer(text):
            output.append(text[cursor:match.start()])
            raw = match.group(1)
            while raw and raw[-1] in ".,;:!?)]}" and not raw.endswith("\\" + raw[-1]):
                raw = raw[:-1]
            ref = "@" + raw
            value = await self.resolve(ref)
            snapshot[ref] = value
            output.append(value if isinstance(value, str) else json.dumps(value))
            cursor = match.start() + len(ref)
        output.append(text[cursor:])
        return "".join(output).replace("@@", "@"), snapshot

# User Python Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Owner-scripted single-file Python tools built into per-tool uv venvs, executed in scoped subprocesses, granted to agent contexts via toolboxes, and authored in a Monaco workbench with AI drafting.

**Architecture:** A new `switchgear_sdk` package (installed into every tool venv) defines the authoring contract; `src/switchgear/usertools/` holds the store, builder, executor, vault, and grants; ready tools register in the existing `ToolRegistry` under a `user:` prefix and flow through the existing `ExecutionPolicy` allowlist. Spec: `docs/superpowers/specs/2026-07-23-user-python-tools-design.md`.

**Tech Stack:** Python 3.12 / FastAPI / SQLite storage layer, `uv` for venvs, React + TypeScript + `@monaco-editor/react`, vitest, pytest.

## Global Constraints

- Backend tests: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest <path> -q`
- Frontend tests: `cd frontend && npm test -- --run <pattern>`
- Tool names match skills' `NAME_RE`: `^[a-z0-9][a-z0-9-]{1,63}$`
- Registered tool names are `user:<name>`; built-ins are never shadowed.
- Subprocess env for tool runs contains ONLY: declared vault names, `PATH`, `HOME` (scratch dir), `LANG`. Never any `SWITCHGEAR_*` value.
- Secret vault values are write-only past the API boundary — no endpoint ever returns them.
- Tool statuses: `draft | building | ready | failed`. Only `ready` tools register.
- Default per-tool timeout 60s; result cap 256 KiB; stdout/stderr cap 64 KiB each.
- Data on disk under `/data/tools/<name>/` (settings-derived root, injectable in tests).
- Follow existing store/route/test patterns (`skills/store.py`, `web/orchestration_routes.py`, `tests/fakes.py`).

---

### Task 1: switchgear_sdk package — decorator, env accessor, schema derivation

**Files:**
- Create: `src/switchgear_sdk/__init__.py`
- Create: `src/switchgear_sdk/introspect.py`
- Test: `tests/test_sdk_introspect.py`

**Interfaces:**
- Produces: `@tool` / `@tool(effect="read", timeout=30)` decorator attaching `fn.__switchgear_tool__` (a `ToolSpec` with `.fn`, `.effect`, `.timeout`); `env(name) -> str` raising `KeyError` with a clear message for missing names; `introspect.load_tool(path) -> fn`; `introspect.derive_schema(fn) -> dict` (JSON schema); `python -m switchgear_sdk.introspect <tool.py>` printing `{"params", "description", "effect", "timeout", "entrypoint"}` JSON.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sdk_introspect.py
import json
import subprocess
import sys

import pytest

from switchgear_sdk import env, tool
from switchgear_sdk.introspect import derive_schema, load_tool


def test_tool_decorator_attaches_spec():
    @tool(effect="read", timeout=30)
    def fetch(company: str, limit: int = 20) -> dict:
        """Fetch roles."""
        return {}

    spec = fetch.__switchgear_tool__
    assert spec.effect == "read" and spec.timeout == 30 and spec.fn is fetch


def test_tool_decorator_bare_defaults_to_write():
    @tool
    def go(x: str) -> dict:
        return {}

    assert go.__switchgear_tool__.effect == "write"


def test_env_missing_raises_clear_error(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    with pytest.raises(KeyError, match="declare it in the tool's env list"):
        env("NOPE_KEY")


def test_derive_schema_types_defaults_required():
    @tool
    def fetch(company: str, limit: int = 20, deep: bool = False) -> dict:
        return {}

    schema = derive_schema(fetch)
    assert schema["properties"]["company"] == {"type": "string"}
    assert schema["properties"]["limit"] == {"type": "integer", "default": 20}
    assert schema["properties"]["deep"] == {"type": "boolean", "default": False}
    assert schema["required"] == ["company"]


def test_load_tool_and_cli_output(tmp_path):
    code = (
        "from switchgear_sdk import tool\n\n"
        "@tool(effect='read')\n"
        "def greet(name: str) -> dict:\n"
        "    \"\"\"Say hello.\"\"\"\n"
        "    return {'hi': name}\n"
    )
    path = tmp_path / "tool.py"
    path.write_text(code)
    fn = load_tool(str(path))
    assert fn.__name__ == "greet"
    out = subprocess.run([sys.executable, "-m", "switchgear_sdk.introspect", str(path)],
                         capture_output=True, text=True, check=True)
    meta = json.loads(out.stdout)
    assert meta["description"] == "Say hello."
    assert meta["effect"] == "read"
    assert meta["entrypoint"] == "greet"
    assert meta["params"]["required"] == ["name"]


def test_load_tool_without_entrypoint_fails(tmp_path):
    path = tmp_path / "tool.py"
    path.write_text("x = 1\n")
    with pytest.raises(RuntimeError, match="no @tool entrypoint"):
        load_tool(str(path))
```

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_sdk_introspect.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'switchgear_sdk'`

- [ ] **Step 3: Implement the package**

```python
# src/switchgear_sdk/__init__.py
"""Authoring SDK for user-scripted switchgear tools.

Installed into every tool venv; also importable by the host app for
introspection tests. Keep dependency-free (httpx helper imports lazily).
"""

import os
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolSpec:
    fn: Callable[..., Any]
    effect: str = "write"
    timeout: int | None = None


def tool(fn: Callable | None = None, *, effect: str = "write",
         timeout: int | None = None):
    def wrap(f: Callable) -> Callable:
        f.__switchgear_tool__ = ToolSpec(fn=f, effect=effect, timeout=timeout)
        return f
    return wrap(fn) if callable(fn) else wrap


def env(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        raise KeyError(f"env entry '{name}' is not available — "
                       "declare it in the tool's env list")
    return value
```

```python
# src/switchgear_sdk/introspect.py
"""Derive a tool's OpenAI param schema from its signature at build time."""

import importlib.util
import inspect
import json
import sys
import types
import typing

_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean",
          list: "array", dict: "object"}


def load_tool(path: str):
    spec = importlib.util.spec_from_file_location("user_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for value in vars(module).values():
        if callable(value) and hasattr(value, "__switchgear_tool__"):
            return value
    raise RuntimeError("no @tool entrypoint found in tool.py")


def _json_type(hint) -> str:
    origin = typing.get_origin(hint)
    if origin in (typing.Union, types.UnionType):  # Optional[T] -> T
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        return _json_type(args[0]) if args else "string"
    return _TYPES.get(origin or hint, "string")


def derive_schema(fn) -> dict:
    hints = typing.get_type_hints(fn)
    props: dict = {}
    required: list[str] = []
    for name, param in inspect.signature(fn).parameters.items():
        props[name] = {"type": _json_type(hints.get(name, str))}
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            props[name]["default"] = param.default
    return {"type": "object", "properties": props, "required": required}


def main() -> None:
    fn = load_tool(sys.argv[1])
    spec = fn.__switchgear_tool__
    print(json.dumps({
        "params": derive_schema(fn),
        "description": inspect.getdoc(fn) or "",
        "effect": spec.effect,
        "timeout": spec.timeout,
        "entrypoint": fn.__name__,
    }))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_sdk_introspect.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/switchgear_sdk tests/test_sdk_introspect.py
git commit -m "feat: add switchgear_sdk decorator, env accessor, and schema introspection"
```

---

### Task 2: SDK runner and http helper

**Files:**
- Create: `src/switchgear_sdk/runner.py`
- Create: `src/switchgear_sdk/http.py`
- Test: `tests/test_sdk_runner.py`

**Interfaces:**
- Produces: `python -m switchgear_sdk.runner <tool.py> <result.json>` — reads `{"args": {...}}` from stdin, calls the entrypoint, writes `{"result": ...}` or `{"error": "ExcType: msg"}` to the result file (user prints stay on stdout/stderr). `switchgear_sdk.http` exposes `get/post(...)` via lazily-imported `httpx` with a 30s timeout and a switchgear UA.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sdk_runner.py
import json
import subprocess
import sys

TOOL = (
    "from switchgear_sdk import tool\n\n"
    "@tool\n"
    "def add(a: int, b: int = 1) -> dict:\n"
    "    print('working...')\n"
    "    return {'sum': a + b}\n"
)

BROKEN = (
    "from switchgear_sdk import tool\n\n"
    "@tool\n"
    "def boom(a: int) -> dict:\n"
    "    raise ValueError('nope')\n"
)


def run_tool(tmp_path, code, args):
    tool_py = tmp_path / "tool.py"
    tool_py.write_text(code)
    result_path = tmp_path / "result.json"
    proc = subprocess.run(
        [sys.executable, "-m", "switchgear_sdk.runner", str(tool_py), str(result_path)],
        input=json.dumps({"args": args}), capture_output=True, text=True)
    return proc, json.loads(result_path.read_text())


def test_runner_writes_result_and_keeps_prints_on_stdout(tmp_path):
    proc, result = run_tool(tmp_path, TOOL, {"a": 2, "b": 3})
    assert result == {"result": {"sum": 5}}
    assert "working..." in proc.stdout


def test_runner_reports_tool_exception(tmp_path):
    proc, result = run_tool(tmp_path, BROKEN, {"a": 1})
    assert result == {"error": "ValueError: nope"}
    assert proc.returncode == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_sdk_runner.py -q`
Expected: FAIL — `No module named switchgear_sdk.runner`

- [ ] **Step 3: Implement**

```python
# src/switchgear_sdk/runner.py
"""Subprocess entrypoint: stdin args -> entrypoint -> result file."""

import json
import sys

from switchgear_sdk.introspect import load_tool


def main() -> None:
    tool_path, result_path = sys.argv[1], sys.argv[2]
    fn = load_tool(tool_path)
    payload = json.load(sys.stdin)
    try:
        out = {"result": fn(**payload.get("args", {}))}
    except Exception as e:  # tool errors are data for the host, not a crash
        out = {"error": f"{type(e).__name__}: {e}"}
    with open(result_path, "w") as fh:
        json.dump(out, fh, default=str)


if __name__ == "__main__":
    main()
```

```python
# src/switchgear_sdk/http.py
"""Thin httpx wrapper with sane defaults for scraper-style tools."""

DEFAULT_TIMEOUT = 30.0
USER_AGENT = "switchgear-tool/1.0"


def _client():
    import httpx
    return httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True,
                        headers={"User-Agent": USER_AGENT})


def get(url: str, **kwargs):
    with _client() as client:
        return client.get(url, **kwargs)


def post(url: str, **kwargs):
    with _client() as client:
        return client.post(url, **kwargs)
```

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_sdk_runner.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear_sdk/runner.py src/switchgear_sdk/http.py tests/test_sdk_runner.py
git commit -m "feat: add sdk subprocess runner and http helper"
```

---

### Task 3: Tool definition model and store

**Files:**
- Create: `src/switchgear/usertools/__init__.py` (empty)
- Create: `src/switchgear/usertools/model.py`
- Create: `src/switchgear/usertools/store.py`
- Test: `tests/test_usertool_store.py`

**Interfaces:**
- Consumes: storage layer (`db.put/get/query/delete`), `skills.model.NAME_RE`.
- Produces: `parse_tool_definition(text: str) -> dict` (JSON text with `name`, `code`, optional `requires`, `env`, `timeout`; raises `ToolDefinitionError`); `ToolDefinitionStore` with `validate(text)`, `save(text, source, status=None) -> record` (status defaults `draft` for owner, `pending`→handled by definition_writes for agent), `get(name)`, `list()`, `delete(name)`, `set_build(name, *, status, params=None, description=None, effect=None, build_log="")`. Collection: `user-tools`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_usertool_store.py
import json

import pytest

from switchgear.usertools.model import ToolDefinitionError, parse_tool_definition
from switchgear.usertools.store import ToolDefinitionStore
from tests.fakes import FakeStorage


def definition(**over):
    doc = {"name": "fetch-jobs", "code": "from switchgear_sdk import tool\n",
           "requires": ["httpx"], "env": ["GH_KEY"], "timeout": 45}
    doc.update(over)
    return json.dumps(doc)


def test_parse_valid_definition():
    doc = parse_tool_definition(definition())
    assert doc["name"] == "fetch-jobs"
    assert doc["requires"] == ["httpx"] and doc["env"] == ["GH_KEY"]
    assert doc["timeout"] == 45


def test_parse_rejects_bad_name_and_missing_code():
    with pytest.raises(ToolDefinitionError, match="invalid name"):
        parse_tool_definition(definition(name="Bad Name"))
    with pytest.raises(ToolDefinitionError, match="code is required"):
        parse_tool_definition(definition(code=""))


def test_parse_defaults():
    doc = parse_tool_definition(json.dumps({"name": "t", "code": "x"}))
    assert doc["requires"] == [] and doc["env"] == [] and doc["timeout"] == 60


@pytest.mark.asyncio
async def test_save_get_list_delete_roundtrip():
    store = ToolDefinitionStore(FakeStorage())
    record = await store.save(definition(), source="owner")
    assert record["status"] == "draft" and record["source"] == "owner"
    assert (await store.get("fetch-jobs"))["code"].startswith("from switchgear_sdk")
    listed = await store.list()
    assert [t["name"] for t in listed] == ["fetch-jobs"]
    assert "code" not in listed[0]  # list is summary-shaped
    assert await store.delete("fetch-jobs") is True
    assert await store.get("fetch-jobs") is None


@pytest.mark.asyncio
async def test_set_build_updates_status_and_derived_fields():
    store = ToolDefinitionStore(FakeStorage())
    await store.save(definition(), source="owner")
    record = await store.set_build(
        "fetch-jobs", status="ready",
        params={"type": "object", "properties": {}, "required": []},
        description="Fetch jobs.", effect="read", build_log="ok")
    assert record["status"] == "ready" and record["effect"] == "read"
    assert record["description"] == "Fetch jobs."
```

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_usertool_store.py -q`
Expected: FAIL — `ModuleNotFoundError: switchgear.usertools`

- [ ] **Step 3: Implement**

```python
# src/switchgear/usertools/model.py
import json

from switchgear.skills.model import NAME_RE

DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 600


class ToolDefinitionError(Exception):
    pass


def parse_tool_definition(text: str) -> dict:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise ToolDefinitionError(f"definition must be JSON: {e}") from None
    if not isinstance(doc, dict):
        raise ToolDefinitionError("definition must be an object")
    name = str(doc.get("name") or "")
    if not NAME_RE.match(name):
        raise ToolDefinitionError("invalid name (lowercase alphanumerics and dashes)")
    if not doc.get("code"):
        raise ToolDefinitionError("code is required")
    requires = doc.get("requires") or []
    env = doc.get("env") or []
    for field, value in (("requires", requires), ("env", env)):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ToolDefinitionError(f"{field} must be a list of strings")
    timeout = doc.get("timeout", DEFAULT_TIMEOUT)
    if not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT:
        raise ToolDefinitionError(f"timeout must be an integer 1-{MAX_TIMEOUT}")
    return {"name": name, "code": str(doc["code"]), "requires": requires,
            "env": env, "timeout": timeout}
```

```python
# src/switchgear/usertools/store.py
import time

from switchgear.storage.base import Storage
from switchgear.usertools.model import parse_tool_definition

COLLECTION = "user-tools"
SUMMARY_FIELDS = ("name", "description", "status", "source", "effect",
                  "requires", "env", "timeout", "updated_at")


class ToolDefinitionStore:
    def __init__(self, storage: Storage):
        self._db = storage

    @staticmethod
    def validate(text: str) -> dict:
        return parse_tool_definition(text)

    async def save(self, text: str, source: str, status: str | None = None) -> dict:
        doc = parse_tool_definition(text)
        existing = await self.get(doc["name"]) or {}
        record = {**existing, **doc, "text": text,
                  "status": status or "draft", "source": source,
                  "updated_at": time.time()}
        record.setdefault("effect", "write")
        record.setdefault("description", "")
        record.setdefault("params", None)
        record.setdefault("build_log", "")
        await self._db.put(COLLECTION, doc["name"], record)
        return record

    async def get(self, name: str) -> dict | None:
        return await self._db.get(COLLECTION, name)

    async def list(self) -> list[dict]:
        docs = await self._db.query(COLLECTION)
        docs.sort(key=lambda d: d["name"])
        return [{k: d.get(k) for k in SUMMARY_FIELDS} for d in docs]

    async def delete(self, name: str) -> bool:
        if await self.get(name) is None:
            return False
        await self._db.delete(COLLECTION, name)
        return True

    async def set_build(self, name: str, *, status: str, params: dict | None = None,
                        description: str | None = None, effect: str | None = None,
                        build_log: str = "") -> dict | None:
        record = await self.get(name)
        if record is None:
            return None
        record.update({"status": status, "build_log": build_log,
                       "updated_at": time.time()})
        if params is not None:
            record["params"] = params
        if description is not None:
            record["description"] = description
        if effect is not None:
            record["effect"] = effect
        await self._db.put(COLLECTION, name, record)
        return record
```

Note: if `FakeStorage` lacks `delete`, add it there mirroring the real storage
interface (check `src/switchgear/storage/base.py` for the exact method name).

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_usertool_store.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/usertools tests/test_usertool_store.py
git commit -m "feat: add user tool definition model and store"
```

---

### Task 4: Vault store

**Files:**
- Create: `src/switchgear/usertools/vault.py`
- Test: `tests/test_vault_store.py`

**Interfaces:**
- Produces: `VaultStore(storage)` with `set(name, value, secret: bool)`, `delete(name) -> bool`, `list() -> [{name, secret, value|None}]` (value `None` when secret), `resolve(names: list[str]) -> dict[str, str]` raising `VaultError` naming missing entries. Collection: `vault`. Env-name validation: `^[A-Z][A-Z0-9_]{0,63}$`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_vault_store.py
import pytest

from switchgear.usertools.vault import VaultError, VaultStore
from tests.fakes import FakeStorage


@pytest.mark.asyncio
async def test_secret_values_are_never_listed():
    vault = VaultStore(FakeStorage())
    await vault.set("GH_KEY", "s3cret", secret=True)
    await vault.set("REGION", "eu", secret=False)
    entries = {e["name"]: e for e in await vault.list()}
    assert entries["GH_KEY"]["value"] is None and entries["GH_KEY"]["secret"] is True
    assert entries["REGION"]["value"] == "eu"


@pytest.mark.asyncio
async def test_resolve_returns_values_and_names_missing():
    vault = VaultStore(FakeStorage())
    await vault.set("GH_KEY", "s3cret", secret=True)
    assert await vault.resolve(["GH_KEY"]) == {"GH_KEY": "s3cret"}
    with pytest.raises(VaultError, match="MISSING_ONE"):
        await vault.resolve(["GH_KEY", "MISSING_ONE"])


@pytest.mark.asyncio
async def test_invalid_name_rejected():
    vault = VaultStore(FakeStorage())
    with pytest.raises(VaultError, match="invalid vault name"):
        await vault.set("bad-name", "x", secret=False)


@pytest.mark.asyncio
async def test_delete():
    vault = VaultStore(FakeStorage())
    await vault.set("GH_KEY", "x", secret=True)
    assert await vault.delete("GH_KEY") is True
    assert await vault.delete("GH_KEY") is False
```

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_vault_store.py -q`
Expected: FAIL — module missing

- [ ] **Step 3: Implement**

```python
# src/switchgear/usertools/vault.py
import re
import time

from switchgear.storage.base import Storage

COLLECTION = "vault"
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class VaultError(Exception):
    pass


class VaultStore:
    def __init__(self, storage: Storage):
        self._db = storage

    async def set(self, name: str, value: str, secret: bool) -> dict:
        if not NAME_RE.match(name):
            raise VaultError("invalid vault name (UPPER_SNAKE, max 64 chars)")
        await self._db.put(COLLECTION, name, {
            "name": name, "value": value, "secret": bool(secret),
            "updated_at": time.time()})
        return {"name": name, "secret": bool(secret)}

    async def delete(self, name: str) -> bool:
        if await self._db.get(COLLECTION, name) is None:
            return False
        await self._db.delete(COLLECTION, name)
        return True

    async def list(self) -> list[dict]:
        docs = await self._db.query(COLLECTION)
        docs.sort(key=lambda d: d["name"])
        return [{"name": d["name"], "secret": d["secret"],
                 "value": None if d["secret"] else d["value"]} for d in docs]

    async def resolve(self, names: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        missing: list[str] = []
        for name in names:
            doc = await self._db.get(COLLECTION, name)
            if doc is None:
                missing.append(name)
            else:
                out[name] = doc["value"]
        if missing:
            raise VaultError(f"missing vault entries: {', '.join(missing)}")
        return out
```

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_vault_store.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/usertools/vault.py tests/test_vault_store.py
git commit -m "feat: add vault store with write-only secrets"
```

---

### Task 5: Tool builder (venv resolve + introspection)

**Files:**
- Create: `src/switchgear/usertools/builder.py`
- Test: `tests/test_usertool_builder.py`

**Interfaces:**
- Consumes: `ToolDefinitionStore.set_build`, sdk path (repo `src/` on sys.path in dev; injectable).
- Produces: `ToolBuilder(store, root: Path, sdk_path: Path, run=_run_subprocess)` with `async build(name) -> record`: writes `tool.py`, creates `.venv` via `uv venv`, installs `requires` + sdk via `uv pip install`, runs introspection with the venv python, flips status. `run` is an injectable `async (argv: list[str], cwd) -> (returncode, stdout, stderr)` so tests never touch the network.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_usertool_builder.py
import json

import pytest

from switchgear.usertools.builder import ToolBuilder
from switchgear.usertools.store import ToolDefinitionStore
from tests.fakes import FakeStorage

META = {"params": {"type": "object", "properties": {}, "required": []},
        "description": "Fetch.", "effect": "read", "timeout": None,
        "entrypoint": "fetch"}


def make(tmp_path, results):
    """results: list of (returncode, stdout, stderr) per subprocess call."""
    calls = []

    async def fake_run(argv, cwd=None):
        calls.append(argv)
        return results[len(calls) - 1]

    store = ToolDefinitionStore(FakeStorage())
    builder = ToolBuilder(store, root=tmp_path, sdk_path=tmp_path / "sdk",
                          run=fake_run)
    return store, builder, calls


@pytest.mark.asyncio
async def test_successful_build_flips_ready_and_stores_schema(tmp_path):
    ok = (0, "", "")
    store, builder, calls = make(
        tmp_path, [ok, ok, (0, json.dumps(META), "")])
    await store.save(json.dumps({"name": "fetch", "code": "code"}), source="owner")
    record = await builder.build("fetch")
    assert record["status"] == "ready"
    assert record["description"] == "Fetch." and record["effect"] == "read"
    assert (tmp_path / "fetch" / "tool.py").read_text() == "code"
    assert calls[0][:2] == ["uv", "venv"]
    assert calls[1][:3] == ["uv", "pip", "install"]


@pytest.mark.asyncio
async def test_failed_install_flips_failed_with_log(tmp_path):
    store, builder, _ = make(
        tmp_path, [(0, "", ""), (1, "", "No solution found for httpxx")])
    await store.save(json.dumps({"name": "fetch", "code": "code",
                                 "requires": ["httpxx"]}), source="owner")
    record = await builder.build("fetch")
    assert record["status"] == "failed"
    assert "No solution found" in record["build_log"]


@pytest.mark.asyncio
async def test_failed_introspection_flips_failed(tmp_path):
    ok = (0, "", "")
    store, builder, _ = make(tmp_path, [ok, ok, (1, "", "SyntaxError: bad")])
    await store.save(json.dumps({"name": "fetch", "code": "def"}), source="owner")
    record = await builder.build("fetch")
    assert record["status"] == "failed" and "SyntaxError" in record["build_log"]
```

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_usertool_builder.py -q`
Expected: FAIL — module missing

- [ ] **Step 3: Implement**

```python
# src/switchgear/usertools/builder.py
import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def _run_subprocess(argv: list[str], cwd=None):
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


class ToolBuilder:
    def __init__(self, store, root: Path, sdk_path: Path, run=_run_subprocess):
        self._store = store
        self._root = Path(root)
        self._sdk = Path(sdk_path)
        self._run = run

    async def build(self, name: str) -> dict | None:
        record = await self._store.get(name)
        if record is None:
            return None
        await self._store.set_build(name, status="building")
        tool_dir = self._root / name
        tool_dir.mkdir(parents=True, exist_ok=True)
        (tool_dir / "tool.py").write_text(record["code"])
        venv = tool_dir / ".venv"
        python = venv / "bin" / "python"
        steps = [
            ["uv", "venv", str(venv)],
            ["uv", "pip", "install", "--python", str(python),
             str(self._sdk), *record.get("requires", [])],
            [str(python), "-m", "switchgear_sdk.introspect",
             str(tool_dir / "tool.py")],
        ]
        log_parts: list[str] = []
        for i, argv in enumerate(steps):
            code, stdout, stderr = await self._run(argv, cwd=str(tool_dir))
            log_parts.append(stderr or stdout)
            if code != 0:
                return await self._store.set_build(
                    name, status="failed", build_log="\n".join(log_parts)[-8000:])
            if i == 2:
                try:
                    meta = json.loads(stdout)
                except json.JSONDecodeError:
                    return await self._store.set_build(
                        name, status="failed",
                        build_log=f"introspection produced invalid JSON:\n{stdout[:2000]}")
        timeout_note = ("" if meta.get("timeout") is None
                        else f"\ntimeout from decorator: {meta['timeout']}s")
        return await self._store.set_build(
            name, status="ready", params=meta["params"],
            description=meta["description"], effect=meta["effect"],
            build_log=("build ok" + timeout_note))
```

Note: a decorator-level `timeout` overrides the manifest default at execution
time; Task 6's executor reads `record["timeout"]` and the registry wrapper
passes the decorator value through `record["build_log"]` only as information.
Keep the manifest `timeout` authoritative (YAGNI: no dual source).

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_usertool_builder.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/usertools/builder.py tests/test_usertool_builder.py
git commit -m "feat: add tool builder with uv venv resolve and introspection"
```

---

### Task 6: Tool executor (scoped subprocess)

**Files:**
- Create: `src/switchgear/usertools/executor.py`
- Test: `tests/test_usertool_executor.py`

**Interfaces:**
- Consumes: tool dir layout from Task 5 (`<root>/<name>/tool.py`, `.venv/bin/python`), `VaultStore.resolve`.
- Produces: `ToolExecutor(root: Path, scratch: Path, python_override: str | None = None)` with `async run(record: dict, args: dict, env_values: dict[str, str]) -> dict` returning `{"result": ..., "stdout": str, "stderr": str, "duration_ms": int}` or `{"error": str, "stdout": ..., "stderr": ..., "duration_ms": ...}`. `python_override` lets tests use `sys.executable` (with the repo's `src/` importable) instead of a built venv.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_usertool_executor.py
import sys

import pytest

from switchgear.usertools.executor import ToolExecutor

TOOL = (
    "import os\n"
    "from switchgear_sdk import tool\n\n"
    "@tool\n"
    "def peek(key: str) -> dict:\n"
    "    print('note')\n"
    "    return {'value': os.environ.get(key), "
    "'leak': os.environ.get('SWITCHGEAR_SESSION_SECRET')}\n"
)

SLOW = (
    "import time\n"
    "from switchgear_sdk import tool\n\n"
    "@tool\n"
    "def nap() -> dict:\n"
    "    time.sleep(30)\n"
    "    return {}\n"
)


def setup_tool(tmp_path, code, name="t"):
    tool_dir = tmp_path / name
    tool_dir.mkdir()
    (tool_dir / "tool.py").write_text(code)
    return {"name": name, "timeout": 60, "env": []}


@pytest.mark.asyncio
async def test_run_returns_result_and_captures_stdout(tmp_path, monkeypatch):
    monkeypatch.setenv("SWITCHGEAR_SESSION_SECRET", "root-secret")
    record = setup_tool(tmp_path, TOOL)
    ex = ToolExecutor(root=tmp_path, scratch=tmp_path / "scratch",
                      python_override=sys.executable)
    out = await ex.run(record, {"key": "GH_KEY"}, {"GH_KEY": "abc"})
    assert out["result"] == {"value": "abc", "leak": None}
    assert "note" in out["stdout"]
    assert out["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_timeout_kills_and_reports(tmp_path):
    record = setup_tool(tmp_path, SLOW)
    record["timeout"] = 1
    ex = ToolExecutor(root=tmp_path, scratch=tmp_path / "scratch",
                      python_override=sys.executable)
    out = await ex.run(record, {}, {})
    assert "timed out after 1s" in out["error"]


@pytest.mark.asyncio
async def test_oversized_result_is_error(tmp_path):
    big = ("from switchgear_sdk import tool\n\n"
           "@tool\n"
           "def big() -> dict:\n"
           "    return {'x': 'a' * 400_000}\n")
    record = setup_tool(tmp_path, big)
    ex = ToolExecutor(root=tmp_path, scratch=tmp_path / "scratch",
                      python_override=sys.executable)
    out = await ex.run(record, {}, {})
    assert "result too large" in out["error"]
```

Note: `python_override=sys.executable` works because the test process runs
under uv with `src/` importable; pass `PYTHONPATH` through in the executor
ONLY when `python_override` is set (see implementation).

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_usertool_executor.py -q`
Expected: FAIL — module missing

- [ ] **Step 3: Implement**

```python
# src/switchgear/usertools/executor.py
import asyncio
import json
import os
import time
from pathlib import Path
from uuid import uuid4

RESULT_CAP = 256 * 1024
LOG_CAP = 64 * 1024


class ToolExecutor:
    def __init__(self, root: Path, scratch: Path, python_override: str | None = None):
        self._root = Path(root)
        self._scratch = Path(scratch)
        self._python_override = python_override

    def _python(self, tool_dir: Path) -> str:
        if self._python_override:
            return self._python_override
        return str(tool_dir / ".venv" / "bin" / "python")

    async def run(self, record: dict, args: dict,
                  env_values: dict[str, str]) -> dict:
        tool_dir = self._root / record["name"]
        self._scratch.mkdir(parents=True, exist_ok=True)
        result_path = self._scratch / f"result-{uuid4().hex}.json"
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(self._scratch), "LANG": "C.UTF-8", **env_values}
        if self._python_override:  # test mode: sdk comes from the repo checkout
            env["PYTHONPATH"] = os.pathsep.join(
                p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p) \
                or str(Path(__file__).resolve().parents[2])
        timeout = record.get("timeout") or 60
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            self._python(tool_dir), "-m", "switchgear_sdk.runner",
            str(tool_dir / "tool.py"), str(result_path),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env, cwd=str(self._scratch))
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(json.dumps({"args": args}).encode()),
                timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return self._frame({"error": f"tool timed out after {timeout}s"},
                               b"", b"", started)
        frame_out, frame_err = stdout[:LOG_CAP], stderr[:LOG_CAP]
        if proc.returncode != 0:
            return self._frame(
                {"error": f"tool process exited {proc.returncode}"},
                frame_out, frame_err, started)
        try:
            raw = result_path.read_text()
        except FileNotFoundError:
            return self._frame({"error": "tool produced no result"},
                               frame_out, frame_err, started)
        finally:
            result_path.unlink(missing_ok=True)
        if len(raw) > RESULT_CAP:
            return self._frame({"error": f"result too large (>{RESULT_CAP} bytes)"},
                               frame_out, frame_err, started)
        return self._frame(json.loads(raw), frame_out, frame_err, started)

    @staticmethod
    def _frame(payload: dict, stdout: bytes, stderr: bytes, started: float) -> dict:
        return {**payload,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "duration_ms": int((time.monotonic() - started) * 1000)}
```

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_usertool_executor.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/usertools/executor.py tests/test_usertool_executor.py
git commit -m "feat: add scoped subprocess tool executor"
```

---

### Task 7: Toolboxes and grant expansion

**Files:**
- Create: `src/switchgear/usertools/toolboxes.py`
- Create: `src/switchgear/usertools/grants.py`
- Test: `tests/test_toolboxes_grants.py`

**Interfaces:**
- Produces: `ToolboxStore(storage)` with `save(name, description, tools) -> doc`, `get`, `list`, `delete` (collection `toolboxes`); `expand_grants(grants: dict | None, boxes: list[dict], ready: set[str]) -> tuple[str, ...]` returning sorted `user:`-prefixed names, silently dropping unknown/not-ready tools and dangling boxes; `dangling_refs(grants, boxes, existing) -> list[str]` for UI warning chips.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_toolboxes_grants.py
import pytest

from switchgear.usertools.grants import dangling_refs, expand_grants
from switchgear.usertools.toolboxes import ToolboxStore
from tests.fakes import FakeStorage

BOXES = [{"name": "scrapers", "tools": ["fetch-gh", "fetch-lever"]},
         {"name": "misc", "tools": ["notify"]}]


def test_expand_grants_boxes_and_loose_tools():
    grants = {"toolboxes": ["scrapers"], "tools": ["notify"]}
    ready = {"fetch-gh", "fetch-lever", "notify"}
    assert expand_grants(grants, BOXES, ready) == (
        "user:fetch-gh", "user:fetch-lever", "user:notify")


def test_expand_drops_not_ready_and_dangling():
    grants = {"toolboxes": ["scrapers", "deleted-box"], "tools": ["ghost"]}
    assert expand_grants(grants, BOXES, {"fetch-gh"}) == ("user:fetch-gh",)


def test_expand_empty_grants():
    assert expand_grants(None, BOXES, {"fetch-gh"}) == ()
    assert expand_grants({}, BOXES, {"fetch-gh"}) == ()


def test_dangling_refs():
    grants = {"toolboxes": ["scrapers", "gone"], "tools": ["ghost", "notify"]}
    assert dangling_refs(grants, BOXES, {"fetch-gh", "fetch-lever", "notify"}) == [
        "tool:ghost", "toolbox:gone"]


@pytest.mark.asyncio
async def test_toolbox_store_roundtrip():
    store = ToolboxStore(FakeStorage())
    await store.save("scrapers", "Job board scrapers", ["fetch-gh"])
    assert (await store.get("scrapers"))["tools"] == ["fetch-gh"]
    assert [b["name"] for b in await store.list()] == ["scrapers"]
    assert await store.delete("scrapers") is True
```

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_toolboxes_grants.py -q`
Expected: FAIL — modules missing

- [ ] **Step 3: Implement**

```python
# src/switchgear/usertools/toolboxes.py
import time

from switchgear.skills.model import NAME_RE
from switchgear.storage.base import Storage

COLLECTION = "toolboxes"


class ToolboxError(Exception):
    pass


class ToolboxStore:
    def __init__(self, storage: Storage):
        self._db = storage

    async def save(self, name: str, description: str, tools: list[str]) -> dict:
        if not NAME_RE.match(name or ""):
            raise ToolboxError("invalid toolbox name")
        doc = {"name": name, "description": description or "",
               "tools": list(tools or []), "updated_at": time.time()}
        await self._db.put(COLLECTION, name, doc)
        return doc

    async def get(self, name: str) -> dict | None:
        return await self._db.get(COLLECTION, name)

    async def list(self) -> list[dict]:
        docs = await self._db.query(COLLECTION)
        docs.sort(key=lambda d: d["name"])
        return docs

    async def delete(self, name: str) -> bool:
        if await self.get(name) is None:
            return False
        await self._db.delete(COLLECTION, name)
        return True
```

```python
# src/switchgear/usertools/grants.py
"""Expand {toolboxes, tools} grants into user: tool allowlist entries."""


def expand_grants(grants: dict | None, boxes: list[dict],
                  ready: set[str]) -> tuple[str, ...]:
    grants = grants or {}
    by_name = {b["name"]: b for b in boxes}
    names = set(grants.get("tools") or [])
    for box in grants.get("toolboxes") or []:
        names |= set(by_name.get(box, {}).get("tools") or [])
    return tuple(sorted(f"user:{n}" for n in names if n in ready))


def dangling_refs(grants: dict | None, boxes: list[dict],
                  existing: set[str]) -> list[str]:
    grants = grants or {}
    box_names = {b["name"] for b in boxes}
    out = [f"tool:{t}" for t in grants.get("tools") or [] if t not in existing]
    out += [f"toolbox:{b}" for b in grants.get("toolboxes") or []
            if b not in box_names]
    return sorted(out)
```

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_toolboxes_grants.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/usertools/toolboxes.py src/switchgear/usertools/grants.py tests/test_toolboxes_grants.py
git commit -m "feat: add toolbox store and grant expansion"
```

---

### Task 8: Registry integration — UserToolService

**Files:**
- Create: `src/switchgear/usertools/service.py`
- Modify: `src/switchgear/tools/base.py` (add `ToolRegistry.names` and `unregister`)
- Test: `tests/test_usertool_service.py`, extend `tests/test_tools_base.py`

**Interfaces:**
- Consumes: `ToolDefinitionStore`, `ToolBuilder`, `ToolExecutor`, `VaultStore`, `ToolRegistry`.
- Produces: `ToolRegistry.names(effect: str | None = None) -> list[str]`; `ToolRegistry.unregister(name)`; `UserToolService(store, builder, executor, vault, registry)` with `async save_and_build(text, source) -> record` (save → build → `refresh_registry`), `async refresh_registry()` (registers every `ready` tool as `user:<name>` with `effect` from the record, `idempotent=False`; unregisters anything else), `async test_run(name, args) -> dict` (full executor frame for the workbench), `async delete(name)`. The registered handler returns ONLY `{"result": ...}`/`{"error": ...}` to the model — stdout/stderr/duration stay in the workbench frame.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_usertool_service.py
import json

import pytest

from switchgear.tools.base import ToolRegistry
from switchgear.usertools.service import UserToolService
from switchgear.usertools.store import ToolDefinitionStore
from switchgear.usertools.vault import VaultStore
from tests.fakes import FakeStorage


class FakeBuilder:
    def __init__(self, store, status="ready"):
        self._store, self._status = store, status

    async def build(self, name):
        return await self._store.set_build(
            name, status=self._status,
            params={"type": "object", "properties": {}, "required": []},
            description="d", effect="read")


class FakeExecutor:
    async def run(self, record, args, env_values):
        return {"result": {"echo": args, "env": env_values},
                "stdout": "s", "stderr": "", "duration_ms": 1}


def make(status="ready"):
    db = FakeStorage()
    store = ToolDefinitionStore(db)
    registry = ToolRegistry()
    svc = UserToolService(store, FakeBuilder(store, status), FakeExecutor(),
                          VaultStore(db), registry)
    return svc, store, registry


@pytest.mark.asyncio
async def test_save_and_build_registers_ready_tool():
    svc, _, registry = make()
    await svc.save_and_build(json.dumps({"name": "echo", "code": "c"}),
                             source="owner")
    assert "user:echo" in registry.names()
    result = json.loads(await registry.execute("user:echo", {"x": 1}))
    assert result["result"]["echo"] == {"x": 1}
    assert "stdout" not in result  # model sees result only


@pytest.mark.asyncio
async def test_failed_build_does_not_register():
    svc, _, registry = make(status="failed")
    await svc.save_and_build(json.dumps({"name": "echo", "code": "c"}),
                             source="owner")
    assert "user:echo" not in registry.names()


@pytest.mark.asyncio
async def test_delete_unregisters():
    svc, _, registry = make()
    await svc.save_and_build(json.dumps({"name": "echo", "code": "c"}),
                             source="owner")
    await svc.delete("echo")
    assert "user:echo" not in registry.names()


@pytest.mark.asyncio
async def test_test_run_returns_full_frame_with_declared_env():
    svc, store, _ = make()
    await svc.save_and_build(
        json.dumps({"name": "echo", "code": "c", "env": ["GH_KEY"]}),
        source="owner")
    await svc._vault.set("GH_KEY", "v", secret=True)
    frame = await svc.test_run("echo", {"a": 1})
    assert frame["stdout"] == "s" and frame["result"]["env"] == {"GH_KEY": "v"}
```

Also extend `tests/test_tools_base.py`:

```python
def test_registry_names_filters_by_effect():
    reg = ToolRegistry()
    reg.register(Tool(name="r", description="", parameters={}, handler=_noop,
                      effect="read"))
    reg.register(Tool(name="w", description="", parameters={}, handler=_noop,
                      effect="write"))
    assert reg.names(effect="read") == ["r"]
    assert sorted(reg.names()) == ["r", "w"]


def test_registry_unregister():
    reg = ToolRegistry()
    reg.register(Tool(name="r", description="", parameters={}, handler=_noop))
    reg.unregister("r")
    reg.unregister("r")  # idempotent
    assert reg.names() == []
```

(`_noop` is `async def _noop(**kwargs): return {}` — add it near the other
test helpers in `tests/test_tools_base.py`.)

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_usertool_service.py tests/test_tools_base.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

In `src/switchgear/tools/base.py`, add to `ToolRegistry`:

```python
    def names(self, effect: str | None = None) -> list[str]:
        return [name for name, tool in self._tools.items()
                if effect is None or tool.effect == effect]

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
```

```python
# src/switchgear/usertools/service.py
import json

from switchgear.tools.base import Tool
from switchgear.usertools.vault import VaultError


class UserToolService:
    def __init__(self, store, builder, executor, vault, registry):
        self.store = store
        self._builder = builder
        self._executor = executor
        self._vault = vault
        self._registry = registry

    async def save_and_build(self, text: str, source: str) -> dict:
        record = await self.store.save(text, source=source)
        record = await self._builder.build(record["name"]) or record
        await self.refresh_registry()
        return record

    async def delete(self, name: str) -> bool:
        ok = await self.store.delete(name)
        await self.refresh_registry()
        return ok

    async def test_run(self, name: str, args: dict) -> dict:
        record = await self.store.get(name)
        if record is None:
            return {"error": "tool not found"}
        return await self._invoke(record, args)

    async def _invoke(self, record: dict, args: dict) -> dict:
        try:
            env_values = await self._vault.resolve(record.get("env") or [])
        except VaultError as e:
            return {"error": str(e), "stdout": "", "stderr": "", "duration_ms": 0}
        return await self._executor.run(record, args, env_values)

    async def refresh_registry(self) -> None:
        current = {n for n in self._registry.names() if n.startswith("user:")}
        ready: set[str] = set()
        for record in await self.store.list():
            if record["status"] != "ready":
                continue
            full = await self.store.get(record["name"])
            name = f"user:{record['name']}"
            ready.add(name)
            self._registry.register(Tool(
                name=name, description=full.get("description") or "",
                parameters=full.get("params")
                or {"type": "object", "properties": {}, "required": []},
                handler=self._handler(full), effect=full.get("effect", "write"),
                idempotent=False))
        for name in current - ready:
            self._registry.unregister(name)

    def _handler(self, record: dict):
        async def run(**args):
            frame = await self._invoke(record, args)
            keep = "error" if "error" in frame else "result"
            return json.dumps({keep: frame[keep]})
        return run
```

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_usertool_service.py tests/test_tools_base.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/usertools/service.py src/switchgear/tools/base.py tests/test_usertool_service.py tests/test_tools_base.py
git commit -m "feat: register ready user tools in the tool registry"
```

---

### Task 9: API routes — tools, toolboxes, vault, grants

**Files:**
- Create: `src/switchgear/web/usertool_routes.py`
- Modify: `src/switchgear/web/deps.py` (add `user_tools`, `toolboxes`, `vault` fields)
- Modify: `src/switchgear/web/app.py` (wire stores/service into `AppState`, call `register_usertool_routes(app, state)`, `await state.user_tools.refresh_registry()` on startup, and pass the tools root `Path(settings.data_dir) / "tools"` — check `config.py` for the exact data-dir setting name and reuse it)
- Test: `tests/test_usertools_api.py`

**Interfaces:**
- Consumes: Task 3–8 objects from `state`.
- Produces routes (all `Depends(auth.require_owner)`):
  - `GET /api/tools` → store.list() plus per-tool `granted_default: bool`
  - `GET /api/tools/{name}` → full record minus nothing (code included; no vault values exist here)
  - `PUT /api/tools/{name}` body `{text}` → `save_and_build` (400 on `ToolDefinitionError`, name-match check like agents route)
  - `DELETE /api/tools/{name}`
  - `POST /api/tools/{name}/test` body `{args}` → full executor frame
  - `GET/PUT/DELETE /api/toolboxes[...]`
  - `GET /api/vault` (write-only values), `PUT /api/vault/{name}` body `{value, secret}`, `DELETE /api/vault/{name}`
  - `PUT /api/conversations/{id}/grants` body `{toolboxes, tools}` (stored on the conversation doc), `GET` returns grants + `dangling`
  - `GET/PUT /api/settings/default-grants` (stored in the `app-settings` collection under key `default_grants`, following `settings_routes.py` patterns)

- [ ] **Step 1: Write the failing tests**

Follow the client/fixture pattern in `tests/test_skills_api.py` (async test
client against the app with fakes). Cover:

```python
# tests/test_usertools_api.py — key assertions (use the standard app fixture)
import json

import pytest


@pytest.mark.asyncio
async def test_put_tool_saves_builds_and_lists(client):
    body = {"text": json.dumps({"name": "echo", "code": "c"})}
    r = await client.put("/api/tools/echo", json=body)
    assert r.status_code == 200 and r.json()["status"] in ("ready", "failed")
    r = await client.get("/api/tools")
    assert [t["name"] for t in r.json()] == ["echo"]


@pytest.mark.asyncio
async def test_put_tool_name_mismatch_400(client):
    body = {"text": json.dumps({"name": "other", "code": "c"})}
    assert (await client.put("/api/tools/echo", json=body)).status_code == 400


@pytest.mark.asyncio
async def test_vault_secret_values_never_returned(client):
    await client.put("/api/vault/GH_KEY", json={"value": "s3cret", "secret": True})
    listed = (await client.get("/api/vault")).json()
    assert listed == [{"name": "GH_KEY", "secret": True, "value": None}]
    assert "s3cret" not in (await client.get("/api/vault")).text


@pytest.mark.asyncio
async def test_conversation_grants_roundtrip_with_dangling(client):
    await client.put("/api/conversations/c1/grants",
                     json={"toolboxes": ["gone"], "tools": []})
    r = await client.get("/api/conversations/c1/grants")
    assert r.json()["dangling"] == ["toolbox:gone"]


@pytest.mark.asyncio
async def test_default_grants_settings(client):
    await client.put("/api/settings/default-grants",
                     json={"toolboxes": ["scrapers"], "tools": []})
    r = await client.get("/api/settings/default-grants")
    assert r.json()["toolboxes"] == ["scrapers"]
```

Wire the app fixture so `state.user_tools` uses `FakeBuilder`/`FakeExecutor`
from Task 8's test module (move them into `tests/fakes.py` in this task so
both files import them from one place).

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_usertools_api.py -q`
Expected: FAIL — routes missing

- [ ] **Step 3: Implement `register_usertool_routes`**

```python
# src/switchgear/web/usertool_routes.py
from fastapi import Depends
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from switchgear import auth
from switchgear.usertools.grants import dangling_refs
from switchgear.usertools.model import ToolDefinitionError
from switchgear.usertools.toolboxes import ToolboxError
from switchgear.usertools.vault import VaultError

SETTINGS_COLLECTION = "app-settings"


class DefinitionPut(BaseModel):
    text: str


class TestRun(BaseModel):
    args: dict = {}


class ToolboxPut(BaseModel):
    description: str = ""
    tools: list[str] = []


class VaultPut(BaseModel):
    value: str
    secret: bool = True


class GrantsPut(BaseModel):
    toolboxes: list[str] = []
    tools: list[str] = []


def register_usertool_routes(app, state) -> None:
    @app.get("/api/tools")
    async def list_tools(email: str = Depends(auth.require_owner)):
        return await state.user_tools.store.list()

    @app.get("/api/tools/{name}")
    async def get_tool(name: str, email: str = Depends(auth.require_owner)):
        doc = await state.user_tools.store.get(name)
        if doc is None:
            raise StarletteHTTPException(404, "tool not found")
        return doc

    @app.put("/api/tools/{name}")
    async def put_tool(name: str, body: DefinitionPut,
                       email: str = Depends(auth.require_owner)):
        try:
            parsed = state.user_tools.store.validate(body.text)
            if parsed["name"] != name:
                raise ToolDefinitionError("tool name does not match URL")
            return await state.user_tools.save_and_build(body.text, source="owner")
        except ToolDefinitionError as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.delete("/api/tools/{name}")
    async def delete_tool(name: str, email: str = Depends(auth.require_owner)):
        if not await state.user_tools.delete(name):
            raise StarletteHTTPException(404, "tool not found")
        return {"ok": True}

    @app.post("/api/tools/{name}/test")
    async def test_tool(name: str, body: TestRun,
                        email: str = Depends(auth.require_owner)):
        return await state.user_tools.test_run(name, body.args)

    @app.get("/api/toolboxes")
    async def list_toolboxes(email: str = Depends(auth.require_owner)):
        return await state.toolboxes.list()

    @app.put("/api/toolboxes/{name}")
    async def put_toolbox(name: str, body: ToolboxPut,
                          email: str = Depends(auth.require_owner)):
        try:
            return await state.toolboxes.save(name, body.description, body.tools)
        except ToolboxError as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.delete("/api/toolboxes/{name}")
    async def delete_toolbox(name: str, email: str = Depends(auth.require_owner)):
        if not await state.toolboxes.delete(name):
            raise StarletteHTTPException(404, "toolbox not found")
        return {"ok": True}

    @app.get("/api/vault")
    async def list_vault(email: str = Depends(auth.require_owner)):
        return await state.vault.list()

    @app.put("/api/vault/{name}")
    async def put_vault(name: str, body: VaultPut,
                        email: str = Depends(auth.require_owner)):
        try:
            return await state.vault.set(name, body.value, body.secret)
        except VaultError as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.delete("/api/vault/{name}")
    async def delete_vault(name: str, email: str = Depends(auth.require_owner)):
        if not await state.vault.delete(name):
            raise StarletteHTTPException(404, "vault entry not found")
        return {"ok": True}

    @app.get("/api/conversations/{conv_id}/grants")
    async def get_grants(conv_id: str, email: str = Depends(auth.require_owner)):
        doc = await state.storage.get("conversations", conv_id) or {}
        grants = doc.get("grants") or {"toolboxes": [], "tools": []}
        boxes = await state.toolboxes.list()
        existing = {t["name"] for t in await state.user_tools.store.list()}
        return {**grants, "dangling": dangling_refs(grants, boxes, existing)}

    @app.put("/api/conversations/{conv_id}/grants")
    async def put_grants(conv_id: str, body: GrantsPut,
                         email: str = Depends(auth.require_owner)):
        doc = await state.storage.get("conversations", conv_id) or {}
        doc["grants"] = {"toolboxes": body.toolboxes, "tools": body.tools}
        await state.storage.put("conversations", conv_id, doc)
        return doc["grants"]

    @app.get("/api/settings/default-grants")
    async def get_default_grants(email: str = Depends(auth.require_owner)):
        doc = await state.storage.get(SETTINGS_COLLECTION, "default_grants")
        return doc or {"toolboxes": [], "tools": []}

    @app.put("/api/settings/default-grants")
    async def put_default_grants(body: GrantsPut,
                                 email: str = Depends(auth.require_owner)):
        doc = {"toolboxes": body.toolboxes, "tools": body.tools}
        await state.storage.put(SETTINGS_COLLECTION, "default_grants", doc)
        return doc
```

In `web/deps.py` add fields: `user_tools: object = None`,
`toolboxes: object = None`, `vault: object = None`.

In `web/app.py` startup wiring (near skill store setup): construct
`ToolDefinitionStore`, `VaultStore`, `ToolboxStore`, `ToolBuilder` (root
`Path(<data dir setting>) / "tools"`, sdk path `Path(switchgear_sdk.__file__).parent`),
`ToolExecutor` (scratch `root / ".scratch"`), `UserToolService`; assign to
state; call `register_usertool_routes(app, state)` next to the other route
registrations; `await state.user_tools.refresh_registry()` in the startup
hook.

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_usertools_api.py -q && UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
Expected: PASS, full suite green

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/web/usertool_routes.py src/switchgear/web/deps.py src/switchgear/web/app.py src/switchgear/usertools/service.py tests
git commit -m "feat: add user tool, toolbox, vault, and grants API routes"
```

---

### Task 10: Chat worker grant enforcement

**Files:**
- Modify: `src/switchgear/web/app.py` (chat worker allowlist construction, around `app.py:499`)
- Test: `tests/test_chat_grants.py`

**Interfaces:**
- Consumes: `expand_grants`, `ToolRegistry.names`, conversation doc `grants`, `app-settings/default_grants`.
- Produces: the chat worker computes `allowlist = [builtin names] + [granted user: names]` each run and passes it to `loop.run(history, allowlist=allowlist)`. New conversations (no `grants` key) fall back to default grants. Ungranted `user:` tools never reach the model's schema list.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chat_grants.py
import pytest

from switchgear.usertools.grants import expand_grants
from switchgear.web.app import build_chat_allowlist  # extracted pure helper


def test_ungranted_user_tools_excluded():
    registry_names = ["plan", "http_fetch", "user:echo", "user:fetch-gh"]
    grants = {"toolboxes": [], "tools": ["echo"]}
    allow = build_chat_allowlist(registry_names, grants, boxes=[],
                                 ready={"echo", "fetch-gh"})
    assert "user:echo" in allow and "user:fetch-gh" not in allow
    assert "http_fetch" in allow and "plan" in allow


def test_no_grants_means_builtins_only():
    allow = build_chat_allowlist(["plan", "user:echo"], None, boxes=[],
                                 ready={"echo"})
    assert allow == ["plan"]
```

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_chat_grants.py -q`
Expected: FAIL — `build_chat_allowlist` missing

- [ ] **Step 3: Implement**

Add near the top of `web/app.py` (module level, pure function):

```python
def build_chat_allowlist(registry_names: list[str], grants: dict | None,
                         boxes: list[dict], ready: set[str]) -> list[str]:
    builtin = [n for n in registry_names if not n.startswith("user:")]
    return builtin + list(expand_grants(grants, boxes, ready))
```

In the chat worker (after loading history, before `loop.run`):

```python
conv_doc = await state.storage.get("conversations", conv_id) or {}
grants = conv_doc.get("grants")
if grants is None:
    grants = await state.storage.get("app-settings", "default_grants")
boxes = await state.toolboxes.list()
ready = {t["name"] for t in await state.user_tools.store.list()
         if t["status"] == "ready"}
allowlist = build_chat_allowlist(state.registry.names(), grants, boxes, ready)
...
async for event in loop.run(history, allowlist=allowlist):
```

Also persist default grants onto new conversations: when `conv_doc` has no
`grants` key and defaults exist, write them back so the sidebar shows the
conversation's actual state.

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_chat_grants.py tests/test_web.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/web/app.py tests/test_chat_grants.py
git commit -m "feat: enforce tool grants in chat runs"
```

---

### Task 11: Agent proposals and AI drafting

**Files:**
- Modify: `src/switchgear/web/app.py` (add `"tool"` to the `definition_writes` stores dict — find where `DefinitionWriteService` is constructed and add `"tool": tool_store`; approval resolution must also trigger `save_and_build`/`refresh_registry`)
- Modify: `src/switchgear/definition_writes.py` (post-approval hook)
- Modify: `src/switchgear/assist.py` (add `"tool"` preset)
- Test: extend `tests/test_agent_writes.py`, `tests/test_usertools_api.py`

**Interfaces:**
- Produces: `DefinitionWriteService(storage, stores, on_approved: dict[str, Callable] = None)` — optional per-kind async callback invoked after an approved save; app wires `{"tool": state.user_tools.rebuild_after_approval}` where `rebuild_after_approval(record)` runs build + refresh. Assist preset `tool`: system prompt instructing the model to return ONLY the JSON definition text (name, code, requires, env, timeout) using the switchgear_sdk contract.

- [ ] **Step 1: Write the failing tests**

```python
# added to tests/test_agent_writes.py
@pytest.mark.asyncio
async def test_approved_tool_definition_triggers_build(...):
    # stores={"tool": tool_store}, on_approved={"tool": recorder}
    # propose valid JSON text -> resolve(approved=True)
    # assert recorder called with the saved record and status flows draft->ready
```

```python
# added to tests/test_usertools_api.py
@pytest.mark.asyncio
async def test_assist_tool_preset_listed(client):
    presets = (await client.get("/api/assist")).json()
    assert {"id": "tool", "name": "Tool generation"} in presets
```

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_agent_writes.py tests/test_usertools_api.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

`definition_writes.py` — constructor takes `on_approved: dict | None = None`;
in `resolve()` after `store.save(...)`:

```python
        if approved:
            saved = await store.save(doc["text"], source="agent", status="active")
            hook = (self._on_approved or {}).get(doc["kind"])
            if hook is not None:
                await hook(saved)
```

Note: user tools approved via this path must save with `status="draft"` and
then build (build decides ready/failed) — pass status through the hook:
`rebuild_after_approval` in `UserToolService`:

```python
    async def rebuild_after_approval(self, record: dict) -> dict | None:
        await self.store.set_build(record["name"], status="draft")
        rebuilt = await self._builder.build(record["name"])
        await self.refresh_registry()
        return rebuilt
```

`assist.py` PRESETS addition:

```python
    "tool": {
        "name": "Tool generation",
        "prompt": ("You write single-file switchgear user tools. Return ONLY a JSON "
                   "object with keys name, code, requires, env, timeout. The code "
                   "defines exactly one function decorated with @tool from "
                   "switchgear_sdk, uses type hints and a docstring (they become the "
                   "schema), reads secrets only via switchgear_sdk.env(NAME) for "
                   "names listed in env, and uses switchgear_sdk.http for requests."),
    },
```

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_agent_writes.py tests/test_usertools_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/definition_writes.py src/switchgear/assist.py src/switchgear/web/app.py tests
git commit -m "feat: gate agent tool authoring through approvals and add tool assist preset"
```

---

### Task 12: Frontend — API bindings and Tools page skeleton

**Files:**
- Create: `frontend/src/api/queries/usertools.ts`
- Create: `frontend/src/pages/tools/ToolsPage.tsx`
- Create: `frontend/src/pages/tools/ToolsPage.module.css`
- Modify: `frontend/src/router.tsx` (route `/tools`), `frontend/src/components/AppShell.tsx` (nav link)
- Test: `frontend/src/pages/tools/ToolsPage.test.tsx`

**Interfaces:**
- Produces: `useTools()`, `useTool(name)`, `useToolboxes()`, `useVault()` react-query hooks; `saveTool(name, text)`, `deleteTool(name)`, `testTool(name, args)`, `saveToolbox`, `putVaultEntry`, `deleteVaultEntry` mutations (follow `frontend/src/api/queries/conversations.ts` + existing mutation patterns, e.g. in the skills page bindings); ToolsPage with left list (tools + toolboxes, status chips via existing `StatusChip`), selection state, and a right detail placeholder. MSW handlers in the test file per `frontend/src/test/msw.ts` conventions.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/tools/ToolsPage.test.tsx
// Using test/utils renderWithProviders + msw server:
// - GET /api/tools -> [{name:"fetch-gh", status:"ready", ...}, {name:"bad", status:"failed"}]
// - GET /api/toolboxes -> [{name:"scrapers", tools:["fetch-gh"]}]
// assert: both tools listed with status chips; toolbox section shows "scrapers";
// clicking a tool selects it (aria-current or data-selected).
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- --run ToolsPage`
Expected: FAIL — module missing

- [ ] **Step 3: Implement** the hooks file, page skeleton (list + selection,
detail pane renders "select a tool"), route, and nav link. Reuse
`RecordTable`/`StatusChip`/`EmptyState` where they fit; keep the page under
~150 lines by splitting the list into `ToolList.tsx` if it grows.

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npm test -- --run ToolsPage`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: add tools page skeleton and api bindings"
```

---

### Task 13: Frontend — Monaco editor, inspector, build status

**Files:**
- Modify: `frontend/package.json` (add `@monaco-editor/react`)
- Create: `frontend/src/pages/tools/ToolEditor.tsx`
- Create: `frontend/src/pages/tools/ToolInspector.tsx`
- Modify: `frontend/src/pages/tools/ToolsPage.tsx`
- Test: `frontend/src/pages/tools/ToolEditor.test.tsx`

**Interfaces:**
- Consumes: Task 12 hooks.
- Produces: `ToolEditor` — Monaco (`language="python"`, theme following app theme) bound to the selected tool's `code`, dirty-state tracking, Save button calling `saveTool` (which PUTs the full JSON text: name, code, requires, env, timeout) and surfacing the returned status; `ToolInspector` — derived `params` rendered read-only (`FieldRenderer` if it fits), editable `requires` (one per line textarea), `env` multi-select from `useVault()` names with an inline "add entry" mini-form, timeout number input, build log shown when status is `failed`. In tests, mock `@monaco-editor/react` with a plain `<textarea>` (vitest `vi.mock`) — Monaco doesn't run under jsdom.

- [ ] **Step 1: Write the failing test** — editing code marks dirty; Save PUTs
assembled JSON text and shows `building → failed` log from the mocked
response; env picker lists vault names.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- --run ToolEditor`
Expected: FAIL

- [ ] **Step 3: Implement** (install with `cd frontend && npm install @monaco-editor/react`).

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npm test -- --run ToolEditor && npm run build`
Expected: PASS, build clean

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: add monaco tool editor and inspector"
```

---

### Task 14: Frontend — test-run panel and AI drafting

**Files:**
- Create: `frontend/src/pages/tools/ToolTestPanel.tsx`
- Create: `frontend/src/pages/tools/ToolDraftBox.tsx`
- Modify: `frontend/src/pages/tools/ToolsPage.tsx`
- Test: `frontend/src/pages/tools/ToolTestPanel.test.tsx`

**Interfaces:**
- Consumes: `testTool(name, args)` (Task 12), `POST /api/assist/tool` (existing assist route + Task 11 preset), `DiffView` component.
- Produces: `ToolTestPanel` — args form generated from `params` schema (string/number/boolean/JSON-textarea for array/object), Run button, result pane with tabs for result JSON / stdout / stderr, duration badge; `ToolDraftBox` — prompt textarea, "Draft with AI" calling assist with `draft` = current editor buffer, response parsed as definition JSON and shown via `DiffView` (old = buffer, new = drafted code) with Apply/Discard; Apply replaces the editor buffer and inspector fields — it never saves.

- [ ] **Step 1: Write the failing test** — schema `{company: string, limit: integer default 20}` renders two inputs with the default prefilled; Run POSTs `{args}` and renders result + stdout tabs; draft Apply replaces buffer without a save call.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- --run ToolTestPanel`
Expected: FAIL

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npm test -- --run ToolTestPanel && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: add tool test-run panel and ai drafting"
```

---

### Task 15: Frontend — conversation grants sidebar and settings

**Files:**
- Create: `frontend/src/pages/chat/GrantsSidebar.tsx`
- Modify: `frontend/src/pages/ChatPage.tsx` (mount sidebar, collapsible)
- Modify: `frontend/src/pages/SettingsPage.tsx` (vault section + default grants section)
- Test: `frontend/src/pages/chat/GrantsSidebar.test.tsx`, extend `frontend/src/pages/SettingsPage.test.tsx`

**Interfaces:**
- Consumes: `GET/PUT /api/conversations/{id}/grants`, `useToolboxes()`, `useTools()`, vault mutations, `GET/PUT /api/settings/default-grants`.
- Produces: `GrantsSidebar({conversationId})` — collapsible right panel listing toolboxes (expandable to member tools) and loose tools with switches; toggling PUTs grants immediately; dangling refs render warning chips. Settings gains "Tool vault" (add entry name/value/secret, list with delete; secret values never displayed) and "Default tool grants" (same toggle list bound to default-grants endpoints).

- [ ] **Step 1: Write the failing tests** — sidebar renders boxes/tools from MSW, toggle fires PUT with updated grants, dangling chip shown; settings vault add + list hides secret values.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- --run GrantsSidebar SettingsPage`
Expected: FAIL

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npm test -- --run GrantsSidebar SettingsPage && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: add grants sidebar and vault settings"
```

---

### Task 16: Docs and seed support

**Files:**
- Create: `docs/user-tools.md` (authoring guide: SDK contract, example scraper, vault, toolboxes, grants, limits)
- Modify: `README.md` (one paragraph + link), `docs/configuration.md` (tools data dir), `src/switchgear/usertools/store.py` (add `seed_dir(path)` mirroring `SkillStore.seed_dir`, reading `user/tools/<name>/tool.json`), `src/switchgear/web/app.py` (call it on boot beside skill seeding)
- Test: extend `tests/test_user_seed_dirs.py`

**Interfaces:**
- Consumes: everything prior.
- Produces: `ToolDefinitionStore.seed_dir(path, source="repo") -> int` seeding definitions that don't already exist (status `draft` — a build still requires an owner save or startup build pass; document this).

- [ ] **Step 1: Write the failing seed test** (a `user/tools/echo/tool.json` fixture seeds one draft record; existing names are not overwritten).

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_user_seed_dirs.py -q`
Expected: FAIL

- [ ] **Step 3: Implement seed_dir + docs.**

- [ ] **Step 4: Run full suites**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q && cd frontend && npm test -- --run && npm run build`
Expected: all green

- [ ] **Step 5: Commit**

```bash
git add docs README.md src tests user 2>/dev/null || git add docs README.md src tests
git commit -m "feat: add user tool docs and seed directory support"
```

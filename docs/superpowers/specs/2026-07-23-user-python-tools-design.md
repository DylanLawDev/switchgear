# User Python Tools, Toolboxes, and the Vault

Date: 2026-07-23
Status: approved

## Purpose

Let the owner script minimal Python tools in an in-app workbench and deliver
them to the agent as first-class tools. The immediate motivation is the
scraping gap — per-site scrapers and thin authenticated API clients that
generic `http_fetch`/browser automation cannot cover — but the product shape
is a general escape hatch: whenever a built-in tool is missing, the owner
writes one.

## Decisions (from brainstorming)

- Execution: subprocess per invocation inside the app container, with a
  constructed environment. The executor interface hides the process launch so
  a harder sandbox (separate container/jail) can replace it later.
- Dependencies: per-tool `requires` resolved by `uv` into a cached per-tool
  venv at save time.
- Secrets: one instance vault of named entries; each tool declares the names
  it needs; only declared names are injected into the subprocess env.
- Grants: deny by default everywhere. Grants attach a toolbox or an
  individual tool to a context (conversation, workflow, agent, skill).
  Conversations get a sidebar with live toggles; Settings holds the default
  grants for new conversations.
- IDE: Monaco-based workbench with manifest inspector, build status, and a
  test-run panel. AI drafting from a prompt, always landing as an editable
  draft. No LSP in v1.
- Tools are single-file (`tool.py`) in v1.

## Data model

New definition stores, following the `skills/store.py` pattern (SQLite via
the storage layer, seedable from the `user/` directory):

**tools** — `name` (kebab, same `NAME_RE` as skills), `description`,
`code` (the `tool.py` source), `requires` (list of PyPI requirement
strings), `env` (list of vault entry names), `timeout` (seconds, default
60), `params` (derived JSON schema, read-only), `effect`
(`read`/`write`, default `write`), `status`
(`draft | building | ready | failed`), `build_log`, `source`
(`owner | agent`), `updated_at`.

**toolboxes** — `name`, `description`, `tools` (list of tool names).
Deleting a box leaves referencing grants resolving to nothing; UIs show a
warning chip for dangling references.

**vault** — named entries, each `{name, value, secret: bool}`. Secret
values are write-only past the API boundary: create/replace/delete only,
never returned by any endpoint. Plain vars are readable in the UI.

**grants** — a uniform shape used in four places: conversations (doc field
`grants`), workflow/agent/skill definitions (a `tools`/`toolboxes`
frontmatter or field), and Settings (`default grants` for new
conversations). A grant is `{toolboxes: [...], tools: [...]}`.

## SDK and authoring contract

A tool file defines exactly one decorated entrypoint:

```python
from switchgear_sdk import tool, env, http

@tool                       # or @tool(effect="read", timeout=30)
def fetch_greenhouse(company: str, limit: int = 20) -> dict:
    """Fetch open roles from a company's Greenhouse board."""
    r = http.get(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs")
    ...
```

- The OpenAI param schema and tool description are derived from the
  signature, type hints, and docstring at build time, introspected inside
  the tool's own venv so imports resolve. The manifest cannot drift from
  the code.
- `switchgear_sdk` is a small package installed into every tool venv:
  `tool` decorator, `env(name)` accessor that raises a clear error for
  undeclared names, and `http` — an `httpx` wrapper with sane
  timeouts/retries/UA defaults.
- Supported param types in v1: `str`, `int`, `float`, `bool`, `list`,
  `dict`, and `Optional`/defaults. Return value must be JSON-serializable.

## Build lifecycle

On save: write source to `/data/tools/<name>/tool.py`, resolve
`requires` + `switchgear_sdk` with `uv` into `/data/tools/<name>/.venv`
(cached; re-resolved only when `requires` changes), then run the
introspection step in that venv to derive `params`. Success flips status
to `ready`; any failure flips to `failed` with the output captured in
`build_log`. Builds run as background tasks; the workbench shows live
status.

## Execution

`ToolExecutor.run(tool, args) -> {result | error, stdout, stderr, duration}`:

- Spawn `/data/tools/<name>/.venv/bin/python -m switchgear_sdk.runner`,
  args JSON on stdin, result JSON on stdout (stdout from user code is
  captured separately and returned for the test panel, truncated).
- Environment contains only: declared vault names, `PATH`, `HOME` (a
  scratch dir), and `LANG`. No `SWITCHGEAR_*` values, ever.
- Parent enforces the tool's timeout (kill on expiry) and an output cap
  (256 KiB result, 64 KiB logs).
- The same executor path serves agent invocations and workbench test runs.

Ready tools register in `ToolRegistry` as `user:<name>` (no shadowing of
built-ins), `effect` from the manifest, `idempotent=False`. Registration
refreshes on save/approve/delete.

## Grants and policy

At policy-build time (each model turn), the active context's grants expand —
toolboxes to member tools, plus individual tools — into `user:` names merged
into `ExecutionPolicy.tools`. Ungranted user tools never appear in the
model's schema list. Toolbox edits therefore propagate to every granting
context on its next turn.

Conversation sidebar: collapsible panel listing toolboxes (expandable to
members) and loose tools, each with a toggle. New conversations copy the
Settings default grants (empty on a fresh instance). Toggles take effect on
the next model turn, including mid-run (see the steering spec).

## Workbench UI

Route `/tools`. Three panes:

- Left: tools and toolboxes with status chips; new-tool and new-box actions.
- Center: Monaco editing `tool.py` (Python highlighting; no LSP).
- Right inspector: derived param schema (read-only), `requires` editor,
  `env` picker backed by the vault (with add-entry shortcut), timeout,
  effect, build log on failure.
- Bottom: test-run panel — an args form generated from the derived schema,
  Run button through the real executor, result pane with stdout, result
  JSON, stderr, duration.

AI drafting: a prompt box ("describe the tool you want"); the assist agent
returns `tool.py` plus suggested `requires`/`env`/`timeout`, shown as a diff
against the editor buffer. The owner reviews, edits, saves; saving triggers
the build. Same flow for revisions. Implemented as a new `assist.py` preset.

Vault management lives in Settings: add/replace/delete entries, secret
values write-only.

## Safety model

The owner is trusted; the agent is not fully trusted (prompt injection via
fetched content). Therefore:

- Agent-authored or agent-edited tool code always lands as a draft through
  the existing `definition_writes` approval gate; only an owner save/approve
  makes code buildable and executable.
- Vault values never appear in API responses or the transcript; the model
  sees only tool outputs.
- The subprocess env exposes only declared vault names — a hijacked tool
  call cannot read the session secret, gateway key, or instance config.
- User tools default to `effect="write"` so plan mode (see the chat spec)
  excludes them unless explicitly marked `effect="read"`.
- Vault writes and tool approvals are audited (existing audit collection).

## Error handling

- Build failures: status `failed`, log surfaced in inspector; tool
  unregistered until a successful rebuild.
- Runtime errors: non-zero exit, timeout, oversized output, or invalid JSON
  result all return a structured `{"error": ...}` to the model (matching
  `ToolRegistry.execute` conventions) and full detail to the test panel.
- Vault entry deleted while declared: execution fails fast with a clear
  error naming the missing entry.
- Concurrent saves: last-write-wins for owner edits; agent proposals use the
  existing `base_updated_at` conflict check in `definition_writes`.

## Testing

- Unit: schema derivation (signatures → JSON schema, including defaults and
  Optional), env construction (only declared names, no `SWITCHGEAR_*`),
  grant expansion into `ExecutionPolicy`, vault write-only invariants.
- Integration: save → build → ready → invoke round-trip with a stub venv;
  timeout kill; output cap; failed build unregisters.
- Frontend: workbench save/build-status flow, test-run panel rendering,
  sidebar toggles affecting the next turn, settings default grants.

## Out of scope (v1)

Python LSP/autocomplete, multi-file tools, a separate sandbox
container/jail, per-tool network egress policy, tool versioning/rollback
beyond the draft/approve cycle, sharing tools between instances.

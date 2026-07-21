# Workflow orchestration

switchgear uses a deliberately small orchestration layer instead of a general-purpose agent framework. Existing `AgentLoop`, tool dispatch, storage, approvals, and model gateway remain the execution primitives; the new layer adds typed definitions, capability boundaries, durable continuation, and user-facing authoring.

## Resource model

- **Tools** are deterministic runtime capabilities with JSON parameter schemas and effect/idempotency metadata.
- **Skills** are Codex-style guidance packages. They teach an agent how to perform a task but do not execute or own schedules.
- **Agent profiles** are reusable `AGENT.md` definitions with an internal prompt, model tier, optional JSON output schema, and optional tool/resource/skill allowlists. Omitted allowlists mean full access; an explicit empty list means no access. Resource rules use slash paths such as `resources/reference-data` and include their descendants.
- **Workflows** are `WORKFLOW.md` manifests. Schema version 2 adds JSON Schema inputs/outputs and an ordered list of `agent`, `tool`, and CEL `transform` steps. Existing schema-version-1 data apps remain supported.
- **Schedules** are stored resources targeting an active executable workflow. They contain a cron or one-time trigger, IANA timezone, overlap policy, and either direct values or a resolver prompt.

The repository ships management skills for agents, workflows, schedules, resources, memories, channels, and skills. Agent-authored definition changes are proposals: the currently active version remains active until owner approval.

## References and embedded help

Typing `@` in a smart text area opens a keyboard-controlled selector. The two roots are `@resources` and `@workflows`; selecting a branch drills into typed children. Examples:

```text
@resources.reference-data.items.0.name
@resources.settings.rows.0.value
@workflows.example
```

JSON values resolve to their native type. CSV resources expose `rows`, `columns`, and `meta`; Markdown and text expose `content` and `meta`. References in workflow inputs are resolved once at run start and stored with the run as a reproducibility snapshot. Use `@@` for a literal `@` in interpolated prompt text.

The star button in supported text areas invokes embedded assistance. Presets share the main agent's tools and combine a fixed internal instruction, the current draft/context, and a short user request. The shipped presets generate prompts, schema-version-2 workflow manifests, and schema-valid workflow parameter objects.

## HTTP API

Owner-authenticated endpoints include:

```text
GET/PUT/DELETE       /api/agents/{name}
POST                 /api/agents/{name}/test
GET/POST             /api/schedules
GET/PUT/DELETE       /api/schedules/{id}
POST                 /api/schedules/{id}/run|enable|disable
GET                  /api/schedules/{id}/runs
POST                 /api/workflows/{name}/runs
GET                  /api/workflows/{name}/runs
PUT                  /api/workflows/{name}/definition
GET                  /api/references/suggest
POST                 /api/references/resolve
GET                  /api/approvals
POST                 /api/assist/{prompt|workflow|parameters}
```

The agent-facing `schedules` tool exposes the same schedule lifecycle, and the `agents`, `workflows`, and `channels` tools expose list/read/propose operations. This keeps natural-language agent interaction on the same service layer as the REST API.

## Durability and approvals

Cloud Scheduler delivers recurring triggers. One-time triggers and workflow continuations use Cloud Tasks. Each task carries its expected step index; stale duplicate deliveries are no-ops. A storage compare-and-set claim prevents concurrent execution of the same step, and schedule firing uses a separate claim to close the overlap-check/start race. Firestore implements claims transactionally; memory storage uses an async lock.

Background proposals appear in Approval Inbox immediately. Proposals created during chat remain inline first and also appear in Inbox if unresolved for 15 minutes (configurable). Resource writes, skill writes, agent/workflow/channel definitions, and workflow actions share the approval router.

At startup, a legacy active skill schedule or old Cloud Scheduler job is migrated to a workflow schedule when exactly one executable workflow declares that skill in its intake. Skills no longer display, execute, or provision schedules themselves.

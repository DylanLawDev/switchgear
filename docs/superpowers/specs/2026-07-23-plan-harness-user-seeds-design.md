# Plan harness, user seed dirs, grammar-only tailoring, recent-chat default

Date: 2026-07-23
Status: approved
Branch: feat/job-pipeline

## Goal

Make it possible to set up a multi-step private automation (e.g. a job-apply
pipeline) on a Switchgear instance **from a chat prompt**, while keeping all
tenant-specific definitions out of the open-source repo. Four independent
pieces ship in one PR:

1. **System/user seed-dir split** — tenant definitions live in a gitignored
   `user/` tree, seeded on boot.
2. **Plan tool + visible checklist** — the chat agent can plan multi-step work,
   persist the plan per conversation, and resume it across turns; the UI
   renders it as a live checklist.
3. **Grammar-only resume tailoring** — code-enforced constraint that tailored
   bullets keep the owner's wording except grammar/tense-level edits, with a
   recorded diff.
4. **Chat opens the most recent conversation** instead of a fresh one.

Explicitly out of scope: channel/scraping changes, email digests, and any
job-hunt workflow content (that is tenant data the owner creates on their own
instance; the repo ships no job workflow).

## 1. System/user seed dirs

New setting `user_dir: str = "user"` (env `SWITCHGEAR_USER_DIR`), gitignored.
Layout mirrors the system seed dirs:

```
user/
  skills/<name>/SKILL.md
  workflows/<name>/WORKFLOW.md
  agents/<name>/AGENT.md
  channels/<name>/CHANNEL.md
  resources/<name>.<kind> (+ .meta.yaml)
```

Each store's `seed_dir(path)` gains a `source` keyword (default preserving
today's behavior: `"repo"` for skills/workflows/agents/channels, `"seed"` for
resources). Lifespan seeds system dirs first, then the matching `user/`
subdirectories with `source="owner"` (resources: `source="seed"`, unchanged
semantics). Rules:

- User-dir definitions activate immediately (`owner` source is trusted, same
  as today's repo seeds).
- Same-origin refresh: a store refreshes a changed definition only when the
  stored doc's source matches the seeding source, so repo updates never
  clobber user definitions and vice versa. Stores whose behavior today is
  insert-only-if-missing (skills, agents) stay insert-only for both sources.
- A name collision across system and user dirs resolves in favor of whichever
  seeded first (system seeds run first); no special handling beyond the
  existing "insert if missing" logic. Documented.

`.gitignore` adds `/user/`. `docs/configuration.md` documents the setting and
layout; README gets one sentence.

## 2. Plan tool + checklist harness

### Backend

- New tool module `src/switchgear/tools/plan.py`:
  - `plan_key_var: contextvars.ContextVar[str]` — the storage key for the
    active plan. The chat worker sets it to the conversation id for the
    duration of the run; unset falls back to `"adhoc"`.
  - `make_plan_tool(storage)` → tool `plan` with ops:
    - `set` — `{tasks: [str, ...], title?}` replaces the plan; all tasks start
      `pending`. Max 30 tasks, task text ≤ 300 chars, title ≤ 120.
    - `check` — `{index: int, status: "pending"|"in_progress"|"done"|"skipped"}`
      updates one task.
    - `read` — `{}`.
  - Every op returns the full plan `{title, tasks: [{text, status}]}` so the
    model and UI always see current state. Docs stored in the `plans`
    collection keyed by `plan_key_var`, with `updated_at`.
- Registered in `build_registry` unconditionally.
- `prompts.system_prompt` gains `plan: str = ""`; when non-empty it appends a
  `## Current plan` section. The chat worker (web/app.py) loads the plan doc
  for the conversation each turn and formats it as a checkbox list
  (`- [x] done / [>] in_progress / [ ] pending / [-] skipped`), so the agent
  resumes mid-plan across turns. The BASE prompt gains one sentence telling
  the agent to use `plan` for multi-step work and keep it updated.

### Frontend

- `MessageList` renders tool items named `plan` as a checklist card
  (title + one row per task with a status glyph) instead of the generic tool
  rendering. Data comes from the tool result JSON. No separate panel; the
  latest card in the transcript reflects current state.

## 3. Grammar-only tailoring

In `resume/tailor.py`:

- `_SYSTEM_PROMPT` tightened: rephrasing is limited to grammar, tense, and
  minor tightening; wording otherwise stays the owner's.
- `validate_selection` gains a code-enforced similarity gate: when a bullet
  provides `text` differing from the source fact, compute
  `difflib.SequenceMatcher(None, text, source).ratio()`; if the ratio is below
  `0.75`, the rewrite is discarded — the bullet falls back to the verbatim
  source text and is recorded as rejected. No error is raised; drift is
  contained, not fatal.
- The selection carries `wording_changes: [{fact_id, original, final,
  accepted: bool}]` (one entry per bullet whose text differed). `TailorPipeline`
  persists it on the resume record so the approval view shows exactly what
  changed.

## 4. Chat opens most recent conversation

In `ChatPage.tsx`: when the URL has no `?c`, no new-chat intent is active, and
the conversations list is non-empty, select the newest conversation
(`conversations[0]`, already sorted by `updated_at` desc) via
`setSearchParams({c: id}, {replace: true})`. "New chat" sets a `wantsNew` flag
(and clears `?c`) so it still opens an empty conversation; a truly empty
instance behaves as today.

## Testing

- Backend: seed-dir source rules (user workflow activates; repo refresh does
  not touch owner-sourced doc; user dir absent is a no-op); plan tool ops,
  bounds, contextvar keying, and system-prompt injection; tailor gate
  (grammar fix accepted, drifted rewrite falls back verbatim + recorded,
  wording_changes persisted on the resume record).
- Frontend: plan checklist rendering from a tool result; most-recent
  conversation selection, new-chat still fresh, empty instance unchanged.
- Full suites + lint + build green before PR.

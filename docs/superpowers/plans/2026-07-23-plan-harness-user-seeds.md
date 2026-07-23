# Plan Harness + User Seed Dirs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the four features in `docs/superpowers/specs/2026-07-23-plan-harness-user-seeds-design.md`: user seed dirs, plan tool + checklist, grammar-only tailoring, most-recent-chat default.

**Architecture:** Extends existing store seed methods with a `source` kwarg; adds one new tool module with a contextvar key; hardens one validator; two focused frontend edits.

**Tech Stack:** FastAPI/pydantic, pytest, React/vitest/msw.

## Global Constraints

- Similarity gate threshold: `difflib.SequenceMatcher(None, text, source).ratio() < 0.75` → verbatim fallback, `accepted: false`.
- Plan bounds: ≤ 30 tasks, task ≤ 300 chars, title ≤ 120; statuses `pending|in_progress|done|skipped`.
- Plan storage: collection `plans`, key from `plan_key_var` contextvar (fallback `"adhoc"`).
- Backend: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest` + ruff; frontend: `npx tsc --noEmit && npm test -- --run`.

### Task 1: Seed-source split + user dirs

**Files:** `src/switchgear/config.py` (add `user_dir: str = "user"`), `src/switchgear/skills/store.py`, `src/switchgear/agents/store.py`, `src/switchgear/workflows/store.py`, `src/switchgear/channels/model.py`, `src/switchgear/resources/store.py` (each `seed_dir` gains `source` kwarg, default matching today; refresh condition becomes `existing.get("source") == source`), `src/switchgear/web/app.py` lifespan (after each system seed, seed `Path(settings.user_dir)/<kind>` with `source="owner"`; resources keep `source="seed"`), `.gitignore` (`/user/`).

**Tests** (`tests/test_user_seed_dirs.py`): user workflow dir seeds active with source owner; repo re-seed with changed text does not touch owner-sourced doc of same name; user dir absent → 0; skills user seed inserts when missing only.

- [ ] Failing tests → implement → suite green → commit "Seed tenant definitions from a gitignored user directory"

### Task 2: Plan tool + prompt injection

**Files:** create `src/switchgear/tools/plan.py` (`plan_key_var: ContextVar`, `make_plan_tool(storage)`; ops set/check/read; returns full plan each op; validation errors return `{error: ...}` like other tools), register in `src/switchgear/tools/__init__.py` `build_registry`; `src/switchgear/prompts.py` `system_prompt(..., plan: str = "")` + one BASE sentence ("For multi-step work, call plan to write a checklist first and keep it updated."); `src/switchgear/web/app.py` chat worker: set `plan_key_var` to conv_id for the run, load `plans/<conv_id>` and pass formatted checklist to `system_prompt`.

**Tests** (`tests/test_plan_tool.py`): set→read round trip; check updates status; bounds rejected (31 tasks, long text); contextvar keys storage doc; formatted plan appears in system prompt via chat worker (use existing chat test harness pattern from `tests/test_web.py`).

- [ ] Failing tests → implement → suite green → commit "Add plan tool with per-conversation checklist"

### Task 3: Grammar-only tailor gate

**Files:** `src/switchgear/resume/tailor.py` (`_SYSTEM_PROMPT` wording; in `validate_selection`, similarity gate + `selection["wording_changes"]` accumulation), `src/switchgear/resume/pipeline.py` (persist `wording_changes` on the resume record).

**Tests** (append `tests/test_resume_tailor.py`, `tests/test_resume_pipeline.py`): near-identical rephrase accepted + recorded `accepted: true`; drifted rewrite falls back to source verbatim + `accepted: false`; record contains `wording_changes`.

- [ ] Failing tests → implement → suite green → commit "Constrain resume tailoring to grammar-level edits"

### Task 4: Plan checklist rendering

**Files:** create `frontend/src/pages/chat/PlanChecklist.tsx` (+ styles in `ChatPage.module.css`); `frontend/src/pages/chat/MessageList.tsx` special-cases `item.kind === "tool" && item.name === "plan"` with a result shaped `{title?, tasks: [{text, status}]}` → checklist card; malformed result falls back to `ToolCallDetails`.

**Tests** (`frontend/src/pages/chat/PlanChecklist.test.tsx` or extend MessageList test): renders title + glyphs per status; malformed → generic tool details.

- [ ] Failing tests → implement → tsc + vitest green → commit "Render agent plans as a checklist in chat"

### Task 5: Most-recent conversation default

**Files:** `frontend/src/pages/ChatPage.tsx`: `wantsNew` state; effect — no `?c`, not wantsNew, conversations non-empty → `setSearchParams({c: conversations[0]._id}, {replace: true})`; `startNewChat` sets wantsNew + clears.

**Tests** (extend ChatPage tests if present, else new): visiting with existing conversations loads newest; new-chat still empty; no conversations → unchanged.

- [ ] Failing tests → implement → green → commit "Open the most recent conversation by default"

### Task 6: Docs + full verification + PR

- `docs/configuration.md`: `SWITCHGEAR_USER_DIR` row + user-dir section; README sentence.
- Full backend suite + ruff; frontend tsc + tests + build.
- Push branch, `gh pr create` (base main) titled "Plan harness, user seed dirs, grammar-only tailoring, recent-chat default".

- [ ] All green → commit docs → open PR

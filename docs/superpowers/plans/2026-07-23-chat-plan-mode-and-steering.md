# Chat Plan Mode, Distinct Plan UI, and Mid-run Steering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A sticky per-conversation plan/normal mode toggle that restricts the agent to read-effect tools + `plan`, a visually distinct plan checklist with pinned progress, and mid-run message steering with queued bubbles.

**Architecture:** Mode lives on the conversation doc and filters the per-turn allowlist in the chat worker. Steering adds an inbox to `ChatRun`; `AgentLoop.run` gains an `interleave` callback that injects queued user messages between model turns; leftovers re-enter the loop before the run finishes. Spec: `docs/superpowers/specs/2026-07-23-chat-plan-mode-and-steering-design.md`.

**Tech Stack:** FastAPI + asyncio, SSE, React + TypeScript, vitest, pytest.

## Global Constraints

- Backend tests: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest <path> -q`
- Frontend tests: `cd frontend && npm test -- --run <pattern>`
- Modes: `"normal" | "plan"`; default `"normal"`; persisted on the conversation doc as `mode`.
- Plan-mode allowlist: `{names with effect == "read"} ∪ {"plan"}` intersected with whatever allowlist grants produced.
- New SSE event types: `queued` (`{id, content}`), `queue_delivered` (`{id}`), `queue_removed` (`{id}`) — extend `ChatEvent` in `frontend/src/api/types.ts` for all three.
- Queue endpoints return 409 when no run is active; the client falls back to a normal send.
- If Task 8 of the user-python-tools plan (`ToolRegistry.names`) is not yet merged, implement `names(effect=None)` here first — both plans guard the same tiny method; whichever lands second skips it.

---

### Task 1: ChatRun inbox

**Files:**
- Modify: `src/switchgear/chat_runs.py`
- Test: extend `tests/test_web.py` or create `tests/test_chat_runs.py` (create if chat_runs has no dedicated file)

**Interfaces:**
- Produces: `ChatRun.post(text) -> str` (returns message id, publishes `{"type": "queued", "id", "content"}`); `ChatRun.drain() -> list[dict]` (returns and clears pending `{"id", "content"}` in order, no events); `ChatRun.remove(msg_id) -> bool` (publishes `{"type": "queue_removed", "id"}` on success); `ChatRunManager.get_active(conversation_id) -> ChatRun | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_runs.py
import asyncio

import pytest

from switchgear.chat_runs import ChatRun, ChatRunManager


@pytest.mark.asyncio
async def test_post_drain_preserves_order_and_publishes():
    run = ChatRun("c1")
    id1 = await run.post("first")
    id2 = await run.post("second")
    assert [e["type"] for e in run.events] == ["queued", "queued"]
    drained = run.drain()
    assert [m["content"] for m in drained] == ["first", "second"]
    assert [m["id"] for m in drained] == [id1, id2]
    assert run.drain() == []


@pytest.mark.asyncio
async def test_remove_undelivered_message():
    run = ChatRun("c1")
    msg_id = await run.post("kill me")
    assert await run.remove(msg_id) is True
    assert run.drain() == []
    assert run.events[-1] == {"type": "queue_removed", "id": msg_id}
    assert await run.remove(msg_id) is False


@pytest.mark.asyncio
async def test_manager_get_active():
    mgr = ChatRunManager()
    assert mgr.get_active("c1") is None
    started = asyncio.Event()
    release = asyncio.Event()

    async def worker(run):
        started.set()
        await release.wait()
        await run.finish()

    run = mgr.start("c1", worker)
    await started.wait()
    assert mgr.get_active("c1") is run
    release.set()
    await run.task
    assert mgr.get_active("c1") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_chat_runs.py -q`
Expected: FAIL — `post` not defined

- [ ] **Step 3: Implement**

In `ChatRun.__init__` add:

```python
        self._inbox: list[dict] = []
```

Add methods:

```python
    async def post(self, text: str) -> str:
        from uuid import uuid4
        msg_id = uuid4().hex
        self._inbox.append({"id": msg_id, "content": text})
        await self.publish({"type": "queued", "id": msg_id, "content": text})
        return msg_id

    def drain(self) -> list[dict]:
        pending, self._inbox = self._inbox, []
        return pending

    async def remove(self, msg_id: str) -> bool:
        before = len(self._inbox)
        self._inbox = [m for m in self._inbox if m["id"] != msg_id]
        if len(self._inbox) == before:
            return False
        await self.publish({"type": "queue_removed", "id": msg_id})
        return True
```

(Move the `uuid4` import to the module top.) In `ChatRunManager`:

```python
    def get_active(self, conversation_id: str) -> "ChatRun | None":
        run = self._runs.get(conversation_id)
        if run and run.task and not run.task.done():
            return run
        return None
```

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_chat_runs.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/chat_runs.py tests/test_chat_runs.py
git commit -m "feat: add steering inbox to chat runs"
```

---

### Task 2: AgentLoop interleave hook

**Files:**
- Modify: `src/switchgear/loop.py`
- Test: extend `tests/test_loop.py`

**Interfaces:**
- Consumes: existing `AgentLoop.run(messages, tier, allowlist)`.
- Produces: `AgentLoop.run(..., interleave: Callable[[], Awaitable[list[str]]] | None = None)` — awaited at the top of every loop iteration; each returned string is appended to the transcript as `{"role": "user", "content": text}` before the gateway call. No other behavior change; `interleave=None` is byte-identical to today.

- [ ] **Step 1: Write the failing test**

Follow the existing fake-gateway pattern in `tests/test_loop.py` (a gateway
whose `stream` yields scripted events). Script two iterations (first response
has a tool call, second has none):

```python
@pytest.mark.asyncio
async def test_interleave_injects_user_messages_between_turns(...):
    injected = [["mid-run correction"], []]

    async def interleave():
        return injected.pop(0) if injected else []

    # gateway scripted: iteration 1 -> tool call; iteration 2 -> plain text done
    events = [e async for e in loop.run(messages, interleave=interleave)]
    done = [e for e in events if e["type"] == "done"][0]
    roles = [m.get("role") for m in done["messages"]]
    # the injected user message appears before the first assistant message
    # of iteration 1 (drained at iteration start) and exactly once
    assert roles.count("user") == 2
    assert [m for m in done["messages"]
            if m.get("content") == "mid-run correction"][0]["role"] == "user"
```

Also assert a `interleave=None` run over the same script produces the same
transcript as before the change (regression guard).

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_loop.py -q`
Expected: FAIL — unexpected keyword `interleave`

- [ ] **Step 3: Implement**

In `loop.py`, change the signature and loop head:

```python
    async def run(self, messages: list[dict], tier: str = "chat",
                  allowlist: list[str] | None = None,
                  interleave=None) -> AsyncIterator[dict]:
        transcript = list(messages)
        usage_total = 0
        tools = self._reg.schemas(allowlist) or None
        for _ in range(self._s.max_loop_iterations):
            if interleave is not None:
                for text in await interleave():
                    transcript.append({"role": "user", "content": text})
            final: dict | None = None
            ...
```

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_loop.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/loop.py tests/test_loop.py
git commit -m "feat: add interleave hook to agent loop"
```

---

### Task 3: Worker steering integration and queue endpoints

**Files:**
- Modify: `src/switchgear/web/app.py` (chat worker + two endpoints)
- Test: `tests/test_chat_steering.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - Worker builds `interleave` that drains the run inbox, publishes `{"type": "queue_delivered", "id"}` + appends user bubbles to `live_items`, and returns contents.
  - After the loop yields `done`, the worker checks `run.drain()`: if messages remain, it appends them to the transcript (publishing `queue_delivered` + user bubbles), saves, and re-enters `loop.run` — the run finishes only with an empty inbox. The final `done` event is published once, after the last loop pass.
  - `POST /api/chat/queue` body `{conversation_id, message}` → `{queued: true, id}` or 409 when no active run.
  - `DELETE /api/chat/queue/{conversation_id}/{msg_id}` → `{ok: true}` or 404 (unknown/delivered), 409 (no active run).

- [ ] **Step 1: Write the failing tests**

Use the app test-client fixture pattern from `tests/test_web.py` with a
scripted fake gateway that (a) blocks its first stream until the test posts a
queue message, then emits a no-tool-call reply, so the queued message is
guaranteed undelivered mid-loop and must be handled by the post-done drain
pass; (b) then emits a second reply for the re-entered loop.

```python
# tests/test_chat_steering.py — behaviors to cover
# 1. POST /api/chat/queue with active run -> {queued: True, id}; the final
#    saved transcript contains the queued message as a user turn and the SSE
#    stream contains queued -> queue_delivered -> (second) done.
# 2. POST /api/chat/queue with no active run -> 409.
# 3. DELETE an undelivered message -> removed, never delivered, transcript
#    does not contain it.
# 4. DELETE unknown id -> 404.
```

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_chat_steering.py -q`
Expected: FAIL — 404 (route missing)

- [ ] **Step 3: Implement**

Inside the chat worker (before constructing the loop):

```python
            async def deliver(drained: list[dict]) -> list[str]:
                out: list[str] = []
                for msg in drained:
                    await run.publish({"type": "queue_delivered", "id": msg["id"]})
                    live_items.append({"kind": "message", "role": "user",
                                       "content": msg["content"]})
                    out.append(msg["content"])
                if drained:
                    await state.conversations.save_live(conv_id, live_items)
                return out

            async def interleave() -> list[str]:
                return await deliver(run.drain())
```

Restructure the loop-consumption block: wrap the existing `async for event in
loop.run(...)` in a `while True:`; on `done`, instead of publishing
immediately, do:

```python
                    elif kind == "done":
                        transcript = event["messages"]
                        leftovers = await deliver(run.drain())
                        if leftovers:
                            for text in leftovers:
                                transcript.append({"role": "user", "content": text})
                            await state.conversations.save(
                                conv_id, transcript, title=user_msg[:60])
                            history = transcript
                            rerun = True
                        else:
                            await state.conversations.save(
                                conv_id, transcript, title=user_msg[:60],
                                clear_live=True)
                            task = asyncio.create_task(_reflect_safely(conv_id))
                            state.reflection_tasks.add(task)
                            task.add_done_callback(state.reflection_tasks.discard)
                            await run.publish({"type": "done",
                                               "usage": event["usage"]})
```

with `rerun` controlling the outer `while` (`break` when the inner loop ends
and `rerun` is false; reset `rerun = False` at the top of each pass). Pass
`interleave=interleave` to `loop.run(history, ...)`.

Endpoints (next to `/api/chat`):

```python
    class QueueRequest(BaseModel):
        conversation_id: str
        message: str

    @app.post("/api/chat/queue")
    async def queue_chat(body: QueueRequest,
                         email: str = Depends(auth.require_owner)):
        run = state.chat_runs.get_active(body.conversation_id)
        if run is None:
            raise StarletteHTTPException(409, "no active run")
        msg_id = await run.post(body.message)
        return {"queued": True, "id": msg_id}

    @app.delete("/api/chat/queue/{conversation_id}/{msg_id}")
    async def unqueue_chat(conversation_id: str, msg_id: str,
                           email: str = Depends(auth.require_owner)):
        run = state.chat_runs.get_active(conversation_id)
        if run is None:
            raise StarletteHTTPException(409, "no active run")
        if not await run.remove(msg_id):
            raise StarletteHTTPException(404, "message not queued")
        return {"ok": True}
```

(`QueueRequest` goes with the other BaseModel definitions in the module.)

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_chat_steering.py tests/test_web.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/web/app.py tests/test_chat_steering.py
git commit -m "feat: deliver queued messages mid-run and add queue endpoints"
```

---

### Task 4: Frontend — enabled composer, queued bubbles, delete

**Files:**
- Modify: `frontend/src/api/types.ts` (ChatEvent variants), `frontend/src/api/sse.ts` (no change expected — verify), `frontend/src/pages/ChatPage.tsx`, `frontend/src/pages/chat/Composer.tsx`, `frontend/src/pages/chat/MessageList.tsx`
- Test: extend `frontend/src/pages/ChatPage.test.tsx`

**Interfaces:**
- Consumes: `POST /api/chat/queue`, `DELETE /api/chat/queue/...`, SSE `queued`/`queue_delivered`/`queue_removed`.
- Produces: Composer loses its `disabled` prop usage during streams (keep the prop for genuinely-disabled cases like no conversation); `TranscriptItem` message variant gains `queueId?: string` and `queueState?: "queued" | "delivered"`; `handleSend` branches: streaming → `apiPost("/api/chat/queue", ...)`, add bubble with `queueState:"queued"`; 409 fallback → normal send. `onEvent` handles the three queue events (delivered flips badge, removed drops bubble). MessageList renders a "queued" badge with a small remove button (`aria-label="remove queued message"`) and a muted "sent mid-run" marker once delivered.

- [ ] **Step 1: Write the failing tests** — mid-stream send POSTs to the queue endpoint and renders a queued badge; `queue_delivered` SSE flips the badge; remove button DELETEs and drops the bubble; queue 409 falls back to a normal send.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- --run ChatPage`
Expected: FAIL

- [ ] **Step 3: Implement.** Keep the queue plumbing in ChatPage (state up
there, presentational badge in MessageList). Remember the SSE stream is
consumed by the original `streamChat` call — queue events arrive on it, so
`onEvent` is the single integration point.

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npm test -- --run ChatPage && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: queue and steer messages from the composer during runs"
```

---

### Task 5: Conversation mode — storage, endpoint, prompt, policy filter

**Files:**
- Modify: `src/switchgear/conversations.py` (`set_mode`), `src/switchgear/web/app.py` (endpoint + worker filter), `src/switchgear/prompts.py` (`plan_mode` param)
- Test: extend `tests/test_conversations.py`, `tests/test_prompts.py`; create `tests/test_plan_mode.py`

**Interfaces:**
- Produces: `ConversationStore.set_mode(conversation_id, mode)` (validates against `{"normal", "plan"}`, merges into doc); `PUT /api/conversations/{id}/mode` body `{mode}` → `{mode}`; `GET /api/conversations/{id}/mode` → `{mode}` (default normal); `system_prompt(..., plan_mode: bool = False)` appending, when true:

```
## Plan mode
You are in plan mode: research with read-only tools and maintain the checklist
with the plan tool, but do not execute changes. End your turn by presenting the
plan for approval; the owner will switch to normal mode to execute.
```

- Worker: `mode = conv_doc.get("mode", "normal")`; when `plan`, filter the allowlist: `read = set(state.registry.names(effect="read")) | {"plan"}; allowlist = [n for n in allowlist if n in read]` (composes with the grants allowlist from the tools plan when present; if that plan hasn't landed, start from `state.registry.names()`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_plan_mode.py
from switchgear.web.app import filter_plan_mode  # extracted pure helper


def test_plan_mode_filters_to_read_and_plan():
    names_by_effect = {"read": ["http_fetch", "read_skill"],
                       "all": ["http_fetch", "read_skill", "send_email", "plan"]}
    out = filter_plan_mode(names_by_effect["all"], names_by_effect["read"])
    assert out == ["http_fetch", "read_skill", "plan"]
```

plus: `set_mode` roundtrip + rejection of unknown modes in
`test_conversations.py`; `plan_mode=True` adds the section and
`plan_mode=False` doesn't in `test_prompts.py`; endpoint PUT/GET in the web
test file.

- [ ] **Step 2: Run to verify failure**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_plan_mode.py tests/test_conversations.py tests/test_prompts.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

`conversations.py`:

```python
    MODES = ("normal", "plan")

    async def set_mode(self, conversation_id: str, mode: str) -> dict:
        if mode not in self.MODES:
            raise ValueError(f"mode must be one of {self.MODES}")
        existing = await self._db.get("conversations", conversation_id) or {}
        existing.update({"mode": mode, "updated_at": time.time()})
        await self._db.put("conversations", conversation_id, existing)
        return {"mode": mode}
```

`web/app.py` module-level helper + endpoint + worker wiring:

```python
def filter_plan_mode(allowlist: list[str], read_names: list[str]) -> list[str]:
    keep = set(read_names) | {"plan"}
    return [n for n in allowlist if n in keep]
```

```python
    class ModePut(BaseModel):
        mode: str

    @app.put("/api/conversations/{conv_id}/mode")
    async def put_mode(conv_id: str, body: ModePut,
                       email: str = Depends(auth.require_owner)):
        try:
            return await state.conversations.set_mode(conv_id, body.mode)
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from None

    @app.get("/api/conversations/{conv_id}/mode")
    async def get_mode(conv_id: str, email: str = Depends(auth.require_owner)):
        doc = await state.storage.get("conversations", conv_id) or {}
        return {"mode": doc.get("mode", "normal")}
```

Worker: read `mode` from the conversation doc alongside grants; pass
`plan_mode=(mode == "plan")` into `system_prompt(...)`; apply
`filter_plan_mode` to the allowlist before `loop.run`. Reread the mode at the
top of each rerun pass (Task 3's `while` loop) so a mid-run toggle applies on
the next pass.

- [ ] **Step 4: Run to verify pass**

Run: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_plan_mode.py tests/test_conversations.py tests/test_prompts.py tests/test_web.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/switchgear/conversations.py src/switchgear/prompts.py src/switchgear/web/app.py tests
git commit -m "feat: add sticky plan mode with read-only policy filtering"
```

---

### Task 6: Frontend — mode toggle in composer

**Files:**
- Modify: `frontend/src/pages/chat/Composer.tsx`, `frontend/src/pages/ChatPage.tsx`, `frontend/src/pages/ChatPage.module.css`, `frontend/src/api/queries/conversations.ts` (mode query + mutation)
- Test: extend `frontend/src/pages/chat/Composer.test.tsx`

**Interfaces:**
- Consumes: `GET/PUT /api/conversations/{id}/mode`.
- Produces: `Composer` gains `mode: "plan" | "normal"` and `onModeChange(mode)` props, rendering `SegmentedToggle` (options Plan/Normal) between the textarea and Send; ChatPage owns the query/mutation (`useConversationMode(id)`, `setConversationMode`), optimistic toggle; `.composer[data-mode="plan"]` gets an accent border tint:

```css
.composer[data-mode="plan"] { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; }
```

(match the composer's existing border/spacing conventions in
`ChatPage.module.css`).

- [ ] **Step 1: Write the failing test** — toggle renders both options, clicking Plan calls `onModeChange("plan")`, `data-mode="plan"` set on the form.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- --run Composer`
Expected: FAIL

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npm test -- --run Composer && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: add plan/normal mode toggle to composer"
```

---

### Task 7: Distinct plan card and pinned plan

**Files:**
- Modify: `frontend/src/pages/chat/PlanChecklist.tsx`, `frontend/src/pages/ChatPage.module.css`, `frontend/src/pages/chat/MessageList.tsx`, `frontend/src/pages/ChatPage.tsx`
- Test: extend `frontend/src/pages/chat/PlanChecklist.test.tsx`

**Interfaces:**
- Consumes: `parsePlanResult` (unchanged).
- Produces: `PlanChecklist({plan, variant?: "card" | "pinned"})` — card variant adds a `PLAN` kicker, title, `n/m done` counter, and a progress bar (`<div className={styles.planProgress}><div style={{width: pct}}/></div>`); pinned variant renders collapsed (kicker + title + counter + bar, tasks expandable via `<details>`). ChatPage derives the latest plan from the transcript (last tool item whose parsed result is a plan) and renders the pinned variant above `MessageList`. CSS:

```css
.planCard {
  border-left: 3px solid var(--accent);
  background: color-mix(in srgb, var(--accent) 6%, transparent);
  border-radius: var(--radius, 6px);
  padding: var(--space-3);
}
.planKicker { font-size: 0.7rem; letter-spacing: 0.08em; color: var(--accent); font-weight: 600; }
.planProgress { height: 3px; background: var(--border, #8883); border-radius: 2px; overflow: hidden; }
.planProgress > div { height: 100%; background: var(--accent); }
.planTask[data-status="in_progress"] { color: var(--accent); }
```

(verify variable names against `theme.ts` / existing module CSS and use the
project's actual tokens).

- [ ] **Step 1: Write the failing tests** — counter shows `1/3 done` for one done of three; progress bar width `33%`±rounding; pinned variant collapsed by default with tasks inside `<details>`; kicker text `PLAN` present.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- --run PlanChecklist`
Expected: FAIL

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run full suites**

Run: `cd frontend && npm test -- --run && npm run build && cd .. && UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
Expected: all green

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: distinct plan card with progress and pinned view"
```

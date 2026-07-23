# Chat Plan Mode, Distinct Plan UI, and Mid-run Steering

Date: 2026-07-23
Status: approved

## Purpose

Three chat improvements: a plan/normal mode toggle beside Send, a visually
distinct plan checklist, and the ability to type while the agent is
responding — with messages delivered into the running loop (steering) or
queued for the next turn.

## Plan mode

**Semantics (plan-then-confirm).** In plan mode the agent's policy is
filtered to read-effect tools plus the `plan` tool: it can research and
produce/update the checklist but cannot execute. The mode is sticky per
conversation — stored on the conversation doc (`mode: "plan" | "normal"`,
default normal) — and stays until flipped. Flipping to normal lets the next
turn execute the plan.

**Mechanics.** The chat worker reads the conversation mode when building the
turn's `ExecutionPolicy`: in plan mode the tool allowlist is intersected
with `{tools where effect == "read"} ∪ {"plan"}`. User tools default to
`effect="write"` (see the tools spec), so they are excluded unless marked
read-only. A short system-prompt addition tells the model it is in plan
mode and must end its turn by presenting the plan for approval rather than
acting. Mode changes mid-run apply from the next model turn (the policy is
rebuilt per turn).

**UI.** A two-state segmented control (`Plan | Normal`, reusing
`SegmentedToggle`) sits beside the Send button in the composer. Plan mode
tints the composer border with the accent color so the state is visible at
a glance. The toggle calls a small endpoint that persists the mode on the
conversation.

## Distinct plan UI

The current `planCard` reads like any other chat bubble. Changes:

- Accent-tinted card: left accent border, subtle accent surface wash, and a
  small "PLAN" kicker label above the title.
- Progress summary in the header: `3/7 done` plus a thin progress bar.
- Task glyphs get fixed-width alignment; `in_progress` tasks show the accent
  color on both glyph and text, not glyph only.
- The most recent plan in a conversation also renders pinned in the chat
  header area (collapsed to title + progress; expandable), so long
  transcripts keep the plan in view. Implementation: `MessageList` already
  parses plan results; the pinned copy derives from the latest one.

## Mid-run steering and queueing

**Server model.** `ChatRun` gains an inbox: `post(text)` appends a pending
user message; the chat worker drains the inbox between model turns of
`AgentLoop` and appends drained messages to the transcript as `user` role
messages before the next gateway call. `AgentLoop.run` accepts an optional
async `interleave` callable the worker uses to inject them. Messages still
undelivered when the run finishes are dispatched immediately as the next
user turn (starting a new run), joined in order.

**API.** `POST /conversations/{id}/messages` while a run is active no longer
409s: it posts to the run's inbox and returns `{queued: true, id}`.
`DELETE /conversations/{id}/queue/{id}` removes a not-yet-delivered message.
Queue state is included in the run's SSE events so all viewers stay in sync.

**UI.** The composer is never disabled during a run. Messages sent mid-run
render immediately as user bubbles with a `queued` badge and a remove
affordance; when the worker delivers one, the badge flips to a subtle
"delivered mid-run" marker and the remove affordance disappears. Enter
still sends; nothing about normal-turn sending changes when no run is
active.

**Interactions.** Steering respects the current mode: a message delivered
mid-run does not change the policy; a mode toggle mid-run applies from the
next model turn. Stop/cancel of a run discards undelivered queue items
(with the bubbles reverting to an editable "not sent" state).

## Error handling

- Inbox post to a run that finishes concurrently: falls through to starting
  a normal turn (server picks; client treats `{queued}` and `{started}`
  responses uniformly).
- SSE viewers joining late reconstruct queue state from the event backlog.
- Deleting a message already delivered returns a conflict; the UI simply
  refreshes state.

## Testing

- Unit: policy filtering in plan mode (read + plan only), inbox
  drain-between-turns ordering, leftover-queue dispatch after run end,
  delete-undelivered semantics.
- Frontend: toggle persistence and composer tinting, queued bubble
  lifecycle (queued → delivered / removed), pinned plan rendering and
  progress summary, composer enabled during runs.

## Out of scope

Editing queued messages in place (delete + retype instead), steering for
workflow/skill runs, multi-viewer conflict resolution beyond SSE state
sync.

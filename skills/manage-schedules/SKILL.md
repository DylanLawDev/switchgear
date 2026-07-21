---
name: manage-schedules
description: Create and maintain one-time or recurring workflow schedules
tools: [schedules, workflows, agents, resources]
---
1. Read the executable workflow and its input schema before creating or changing a schedule.
2. Use direct mode for known values and @ references. Use prompt mode when an agent must discover or derive parameters.
3. Store an explicit IANA timezone. Leave overlapping runs disabled unless concurrent execution is intentionally safe.
4. Use the `schedules` tool to create, update, pause, resume, run, or delete the schedule and report the resulting ID.

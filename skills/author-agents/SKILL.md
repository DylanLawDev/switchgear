---
name: author-agents
description: Create or safely modify reusable agent profiles and their permissions
tools: [agents, resources]
---
1. Read the existing profile when modifying one.
2. Define a focused internal prompt, model tier, and optional structured output schema.
3. Omit tools/resources/skills only when full access is intended. Use explicit lists to create a default-deny profile; resource rules use slash paths such as `resources/reference-data`.
4. Propose the complete AGENT.md through the `agents` tool and tell the owner it awaits Inbox approval.

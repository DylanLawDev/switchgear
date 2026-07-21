---
name: author-workflows
description: Create or safely modify manifest-driven executable workflows
tools: [workflows, agents, resources]
---
1. Read the target workflow before editing it. For a new workflow, inspect related workflows for conventions.
2. Keep tools deterministic, skills instructional, and agent steps bounded by named profiles where restrictions are useful.
3. Declare JSON Schema inputs and outputs. Use ordered agent, tool, and CEL transform steps with unique IDs.
4. Validate references, schemas, and prior-step dependencies, then call `workflows` with `op: propose` and the complete WORKFLOW.md.
5. Report that the definition is waiting in the Approval Inbox; never claim it is active before approval.

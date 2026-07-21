import asyncio

import pytest

from switchgear.agents.model import AgentProfileError, parse_agent_profile
from switchgear.agents.store import AgentProfileStore
from switchgear.config import Settings
from switchgear.references import ReferenceError, ReferenceService
from switchgear.resources.store import ResourceStore
from switchgear.storage.memory import MemoryStorage
from switchgear.tools.base import ExecutionPolicy, Tool, ToolRegistry, use_policy
from switchgear.workflows.runner import WorkflowRunBusy, WorkflowRunner
from switchgear.workflows.store import WorkflowStore


PROFILE = """---
schema_version: 1
name: locked-agent
description: A constrained test agent
model_tier: bulk
tools: []
resources: [resources/profile-data]
skills: [author-workflows]
output_schema:
  type: object
  required: [ok]
  properties:
    ok: {type: boolean}
---
Return the requested structured result.
"""

WORKFLOW = """---
schema_version: 2
name: math-flow
description: A deterministic test workflow
execution:
  inputs:
    type: object
    required: [value]
    properties:
      value: {type: integer}
  outputs:
    type: integer
  steps:
    - id: add-one
      type: transform
      expression: inputs.value + 1
    - id: double
      type: transform
      expression: steps['add-one'].output * 2
  output: steps.double.output
---
Test workflow.
"""


def test_agent_profiles_preserve_explicit_empty_capability_sets():
    parsed = parse_agent_profile(PROFILE)
    assert parsed["tools"] == []
    assert parsed["resources"] == ["resources/profile-data"]
    policy = AgentProfileStore.policy(parsed)
    assert policy.allows_tool("http_fetch") is False
    assert policy.allows_resource("resources/profile-data/content") is True
    assert policy.allows_resource("resources/private") is False


def test_agent_profile_rejects_invalid_output_schema():
    with pytest.raises(AgentProfileError, match="invalid output_schema"):
        parse_agent_profile(PROFILE.replace("type: object", "type: imaginary", 1))


async def test_reference_catalog_resolves_native_values_and_enforces_policy():
    db = MemoryStorage()
    settings = Settings(_env_file=None)
    resources = ResourceStore(db, settings)
    workflows = WorkflowStore(db, generators=set(), executors=set())
    refs = ReferenceService(resources, workflows)
    await resources.save("profile-data", "json", "Profile", '{"region":"west"}')
    assert await refs.resolve("@resources.profile-data.region") == "west"
    rendered, snapshot = await refs.interpolate(
        "Email me@example.com; use @resources.profile-data.region.")
    assert rendered == "Email me@example.com; use west."
    assert snapshot == {"@resources.profile-data.region": "west"}
    roots = await refs.suggest()
    assert {row["path"] for row in roots} == {"@resources", "@workflows"}
    with use_policy(ExecutionPolicy(resources=("resources/other",))):
        with pytest.raises(ReferenceError, match="access denied"):
            await refs.resolve("@resources.profile-data.region")


class NoAgents:
    async def run(self, *args, **kwargs):  # pragma: no cover - transform-only workflow
        raise AssertionError("agent should not run")


class NoReferences:
    async def interpolate(self, value):
        return value, {}

    async def resolve(self, value):
        raise AssertionError(value)


async def test_workflow_runner_is_ordered_and_stale_deliveries_are_noops():
    db = MemoryStorage()
    store = WorkflowStore(db, generators=set(), executors=set())
    await store.save(WORKFLOW, source="owner")
    runner = WorkflowRunner(store, db, ToolRegistry(), NoAgents(), NoReferences())
    run = await runner.start("math-flow", {"value": 4})
    first = await runner.advance(run["id"], expected_step_index=0)
    assert first["steps"]["add-one"]["output"] == 5
    stale = await runner.advance(run["id"], expected_step_index=0)
    assert stale["step_index"] == 1 and "double" not in stale["steps"]
    done = await runner.run_to_completion(run["id"])
    assert done["status"] == "succeeded" and done["output"] == 10


async def test_workflow_step_claim_prevents_concurrent_side_effects():
    db = MemoryStorage()
    store = WorkflowStore(db, generators=set(), executors=set())
    tool_workflow = WORKFLOW.replace(
        "type: transform\n      expression: inputs.value + 1",
        "type: tool\n      tool: slow\n      args: {}",
    ).replace("steps['add-one'].output * 2", "inputs.value * 2")
    await store.save(tool_workflow, source="owner")
    started = asyncio.Event()
    release = asyncio.Event()
    registry = ToolRegistry()

    async def slow():
        started.set()
        await release.wait()
        return 5

    registry.register(Tool("slow", "slow", {"type": "object"}, slow))
    runner = WorkflowRunner(store, db, registry, NoAgents(), NoReferences())
    run = await runner.start("math-flow", {"value": 4})
    first = asyncio.create_task(runner.advance(run["id"], 0))
    await started.wait()
    with pytest.raises(WorkflowRunBusy):
        await runner.advance(run["id"], 0)
    release.set()
    await first


async def test_skipped_step_does_not_validate_null_against_output_schema():
    workflow = """---
schema_version: 2
name: skip-flow
description: Skip a typed conditional step
execution:
  inputs: {type: object}
  outputs: {type: string}
  steps:
    - id: conditional
      type: transform
      when: "false"
      expression: '"never"'
      output_schema: {type: string}
    - id: finish
      type: transform
      expression: '"done"'
  output: steps.finish.output
---
Test workflow.
"""
    db = MemoryStorage()
    store = WorkflowStore(db, generators=set(), executors=set())
    await store.save(workflow, source="owner")
    runner = WorkflowRunner(store, db, ToolRegistry(), NoAgents(), NoReferences())
    run = await runner.start("skip-flow", {})
    done = await runner.run_to_completion(run["id"])
    assert done["status"] == "succeeded"
    assert done["steps"]["conditional"] == {
        "status": "skipped", "output": None,
        "started_at": done["steps"]["conditional"]["started_at"],
        "finished_at": done["steps"]["conditional"]["finished_at"],
    }
    assert done["output"] == "done"

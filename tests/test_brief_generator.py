from switchgear.gateway import Completion
from switchgear.storage.memory import MemoryStorage
from switchgear.workflows.model import parse_workflow
from switchgear.workflows.plugins.brief import LlmBriefGenerator

RESEARCH = """---
schema_version: 1
name: research
description: research workflow
items:
  label: source
  label_plural: sources
  title_field: title
  fields:
    title:   {type: text}
    url:     {type: url}
    summary: {type: markdown}
artifacts:
  label: brief
  label_plural: briefs
  title_field: title
  fields:
    title:      {type: text}
    body:       {type: markdown}
    created_at: {type: timestamp}
intake:
  skills: []
---
Body.
"""

ITEM = {"key": "itm-abc", "title": "Agents in prod",
        "url": "https://example.com/a", "summary": "A useful writeup."}


class FakeGateway:
    def __init__(self, content="## Brief\n- point one"):
        self.content = content
        self.calls = []

    async def complete(self, tier, messages, tools=None):
        self.calls.append((tier, messages))
        return Completion(message={"role": "assistant", "content": self.content},
                          usage=42)


def wf():
    return parse_workflow(RESEARCH, generators=set(), executors=set())


async def test_generate_writes_artifact_with_lineage():
    gw, storage = FakeGateway(), MemoryStorage()
    gen = LlmBriefGenerator(gw, storage)
    out = await gen.generate(wf(), dict(ITEM))
    assert out["ok"] is True and out["usage"] == 42
    stored = await storage.get("wf-research-artifacts", out["key"])
    assert stored["item_key"] == "itm-abc"
    assert stored["title"] == "Brief: Agents in prod"
    assert stored["body"].startswith("## Brief")
    assert isinstance(stored["created_at"], float)


async def test_generate_uses_writing_tier_and_grounds_on_item():
    gw = FakeGateway()
    gen = LlmBriefGenerator(gw, MemoryStorage())
    await gen.generate(wf(), dict(ITEM))
    tier, messages = gw.calls[0]
    assert tier == "writing"
    assert "https://example.com/a" in messages[1]["content"]
    assert "do not invent" in messages[0]["content"]


async def test_generate_empty_model_reply_errors_without_writing():
    gw, storage = FakeGateway(content="  "), MemoryStorage()
    gen = LlmBriefGenerator(gw, storage)
    out = await gen.generate(wf(), dict(ITEM))
    assert "empty" in out["error"]
    assert await storage.query("wf-research-artifacts") == []


async def test_generate_requires_artifacts_kind():
    no_artifacts = RESEARCH.replace("artifacts:", "artifacts_gone:")
    parsed = parse_workflow(no_artifacts, generators=set(), executors=set())
    out = await LlmBriefGenerator(FakeGateway(), MemoryStorage()).generate(
        parsed, dict(ITEM))
    assert "no artifacts" in out["error"]

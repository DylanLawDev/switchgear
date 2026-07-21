import json

import pytest

from switchgear.gateway import Completion
from switchgear.jobs.model import make_job
from switchgear.jobs.scoring import ScoringError, score_batch


class FakeCompleteGateway:
    def __init__(self, completions):
        self._completions = list(completions)
        self.calls: list[dict] = []

    async def complete(self, tier, messages, tools=None):
        self.calls.append({"tier": tier, "messages": list(messages)})
        return self._completions.pop(0)


def _job(suffix, **kwargs):
    defaults = dict(
        url=f"https://boards.greenhouse.io/acme/jobs/{suffix}",
        title=f"Engineer {suffix}",
        company="Acme",
        location="Remote",
        description=f"desc-{suffix}",
        source="greenhouse",
    )
    defaults.update(kwargs)
    return make_job(**defaults)


async def test_happy_path_scores_two_jobs():
    job1 = _job(1)
    job2 = _job(2)
    content = json.dumps([
        {"key": job1["key"], "score": 80, "rationale": "Good fit"},
        {"key": job2["key"], "score": 40, "rationale": "Meh fit"},
    ])
    gateway = FakeCompleteGateway([Completion(message={"content": content}, usage=10)])

    results = await score_batch(gateway, "Software engineer", [job1, job2])

    assert results == [
        {"key": job1["key"], "score": 80, "rationale": "Good fit"},
        {"key": job2["key"], "score": 40, "rationale": "Meh fit"},
    ]
    assert gateway.calls[0]["tier"] == "bulk"


async def test_fenced_json_block_parses():
    job1 = _job(1)
    body = json.dumps([{"key": job1["key"], "score": 55, "rationale": "ok"}])
    content = f"```json\n{body}\n```"
    gateway = FakeCompleteGateway([Completion(message={"content": content}, usage=5)])

    results = await score_batch(gateway, "summary", [job1])

    assert results == [{"key": job1["key"], "score": 55, "rationale": "ok"}]


async def test_plain_fence_without_json_tag_parses():
    job1 = _job(1)
    body = json.dumps([{"key": job1["key"], "score": 30, "rationale": "ok"}])
    content = f"```\n{body}\n```"
    gateway = FakeCompleteGateway([Completion(message={"content": content}, usage=5)])

    results = await score_batch(gateway, "summary", [job1])

    assert results == [{"key": job1["key"], "score": 30, "rationale": "ok"}]


async def test_score_150_clamps_to_100():
    job1 = _job(1)
    content = json.dumps([{"key": job1["key"], "score": 150, "rationale": "great"}])
    gateway = FakeCompleteGateway([Completion(message={"content": content}, usage=1)])

    results = await score_batch(gateway, "summary", [job1])

    assert results[0]["score"] == 100


async def test_score_negative_5_clamps_to_0():
    job1 = _job(1)
    content = json.dumps([{"key": job1["key"], "score": -5, "rationale": "bad"}])
    gateway = FakeCompleteGateway([Completion(message={"content": content}, usage=1)])

    results = await score_batch(gateway, "summary", [job1])

    assert results[0]["score"] == 0


async def test_unknown_key_is_dropped():
    job1 = _job(1)
    content = json.dumps([
        {"key": job1["key"], "score": 70, "rationale": "fine"},
        {"key": "not-in-batch", "score": 10, "rationale": "x"},
    ])
    gateway = FakeCompleteGateway([Completion(message={"content": content}, usage=1)])

    results = await score_batch(gateway, "summary", [job1])

    assert len(results) == 1
    assert results[0]["key"] == job1["key"]


async def test_garbage_content_raises_scoring_error():
    job1 = _job(1)
    gateway = FakeCompleteGateway([Completion(message={"content": "not json at all"}, usage=1)])

    with pytest.raises(ScoringError):
        await score_batch(gateway, "summary", [job1])


async def test_non_list_json_raises_scoring_error():
    job1 = _job(1)
    content = json.dumps({"key": job1["key"], "score": 50, "rationale": "x"})
    gateway = FakeCompleteGateway([Completion(message={"content": content}, usage=1)])

    with pytest.raises(ScoringError):
        await score_batch(gateway, "summary", [job1])


async def test_prompt_contains_summary_and_truncated_description():
    job1 = _job(1, description="B" * 5000)
    gateway = FakeCompleteGateway([Completion(message={"content": "[]"}, usage=1)])

    await score_batch(gateway, "Backend engineer with Python focus", [job1])

    prompt_text = gateway.calls[0]["messages"][-1]["content"]
    assert "Backend engineer with Python focus" in prompt_text
    assert job1["key"] in prompt_text
    assert job1["title"] in prompt_text
    assert job1["company"] in prompt_text
    assert "B" * 3000 in prompt_text
    assert "B" * 3001 not in prompt_text

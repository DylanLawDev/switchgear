import json

from switchgear.config import Settings
from switchgear.gateway import Completion
from switchgear.jobs.model import make_job
from switchgear.jobs.scoring import BATCH_SIZE, DEFAULT_CAREER_SUMMARY
from switchgear.storage.memory import MemoryStorage
from switchgear.tools.score_jobs import make_score_jobs_tool

S = Settings(_env_file=None)


class FakeCompleteGateway:
    def __init__(self, scripts):
        self._scripts = list(scripts)
        self.calls: list[dict] = []

    async def complete(self, tier, messages, tools=None):
        self.calls.append({"tier": tier, "messages": list(messages)})
        item = self._scripts.pop(0)
        if isinstance(item, Exception):
            raise item
        return Completion(message={"content": item}, usage=1)


def _job(i, **kwargs):
    defaults = dict(
        url=f"https://boards.greenhouse.io/acme/jobs/{i}",
        title=f"Engineer {i}",
        company="Acme",
        location="Remote",
        description=f"desc-{i}",
        source="greenhouse",
    )
    defaults.update(kwargs)
    return make_job(**defaults)


def _scored_job(i, score=90, rationale="already scored", scored_at=111.0):
    job = _job(i)
    job["score"] = score
    job["rationale"] = rationale
    job["scored_at"] = scored_at
    return job


def _score_content(jobs, base_score=50):
    return json.dumps([
        {"key": job["key"], "score": base_score + idx, "rationale": f"fit {idx}"}
        for idx, job in enumerate(jobs)
    ])


async def test_scores_twelve_jobs_across_two_batches_and_persists():
    storage = MemoryStorage()
    jobs = [_job(i) for i in range(12)]
    for job in jobs:
        await storage.put("jobs", job["key"], job)

    batch1 = jobs[:BATCH_SIZE]
    batch2 = jobs[BATCH_SIZE:]
    gateway = FakeCompleteGateway([_score_content(batch1), _score_content(batch2)])

    tool = make_score_jobs_tool(S, storage, gateway)
    result = await tool.handler()

    assert len(gateway.calls) == 2
    assert result["scored_count"] == 12
    assert result["errors"] == []

    scores = [item["score"] for item in result["scored"]]
    assert scores == sorted(scores, reverse=True)
    assert {item["key"] for item in result["scored"]} == {job["key"] for job in jobs}
    for item in result["scored"]:
        assert set(item) == {"key", "title", "company", "url", "location",
                              "score", "rationale"}

    for job in jobs:
        stored = await storage.get("jobs", job["key"])
        assert stored["score"] is not None
        assert stored["rationale"]
        assert stored["scored_at"] is not None


async def test_career_summary_seeded_on_first_call():
    storage = MemoryStorage()
    gateway = FakeCompleteGateway([])

    tool = make_score_jobs_tool(S, storage, gateway)
    result = await tool.handler()

    assert result["scored_count"] == 0
    assert await storage.get("settings", "career_summary") == DEFAULT_CAREER_SUMMARY


async def test_existing_career_summary_is_not_overwritten():
    storage = MemoryStorage()
    await storage.put("settings", "career_summary", "Custom summary")
    gateway = FakeCompleteGateway([])

    tool = make_score_jobs_tool(S, storage, gateway)
    await tool.handler()

    assert await storage.get("settings", "career_summary") == "Custom summary"


async def test_already_scored_jobs_are_not_resent():
    storage = MemoryStorage()
    already = _scored_job(0)
    unscored = _job(1)
    await storage.put("jobs", already["key"], already)
    await storage.put("jobs", unscored["key"], unscored)

    gateway = FakeCompleteGateway([_score_content([unscored])])

    tool = make_score_jobs_tool(S, storage, gateway)
    result = await tool.handler()

    assert len(gateway.calls) == 1
    prompt = gateway.calls[0]["messages"][-1]["content"]
    assert unscored["key"] in prompt
    assert already["key"] not in prompt
    assert result["scored_count"] == 1

    stored_already = await storage.get("jobs", already["key"])
    assert stored_already["score"] == 90
    assert stored_already["scored_at"] == 111.0


async def test_one_failed_batch_still_lets_other_batch_score():
    storage = MemoryStorage()
    jobs = [_job(i) for i in range(11)]
    for job in jobs:
        await storage.put("jobs", job["key"], job)

    batch1 = jobs[:BATCH_SIZE]
    batch2 = jobs[BATCH_SIZE:]
    gateway = FakeCompleteGateway(["not valid json", _score_content(batch2)])

    tool = make_score_jobs_tool(S, storage, gateway)
    result = await tool.handler()

    assert result["errors"] != []
    assert result["scored_count"] == len(batch2)

    for job in batch1:
        stored = await storage.get("jobs", job["key"])
        assert stored["score"] is None

    for job in batch2:
        stored = await storage.get("jobs", job["key"])
        assert stored["score"] is not None


async def test_gateway_failure_in_one_batch_does_not_abandon_others():
    storage = MemoryStorage()
    jobs = [_job(i) for i in range(11)]
    for job in jobs:
        await storage.put("jobs", job["key"], job)

    batch1 = jobs[:BATCH_SIZE]
    batch2 = jobs[BATCH_SIZE:]
    gateway = FakeCompleteGateway([RuntimeError("boom"), _score_content(batch2)])

    tool = make_score_jobs_tool(S, storage, gateway)
    result = await tool.handler()

    assert len(gateway.calls) == 2
    assert result["scored_count"] == len(batch2)
    assert len(result["errors"]) == 1
    assert "boom" in result["errors"][0]

    for job in batch1:
        stored = await storage.get("jobs", job["key"])
        assert stored["score"] is None

    for job in batch2:
        stored = await storage.get("jobs", job["key"])
        assert stored["score"] is not None


async def test_limit_restricts_number_of_jobs_considered():
    storage = MemoryStorage()
    jobs = [_job(i) for i in range(3)]
    for job in jobs:
        await storage.put("jobs", job["key"], job)

    limited = jobs[:2]
    gateway = FakeCompleteGateway([_score_content(limited)])

    tool = make_score_jobs_tool(S, storage, gateway)
    result = await tool.handler(limit=2)

    assert result["scored_count"] == 2
    assert len(gateway.calls) == 1
    stored_remaining = await storage.get("jobs", jobs[2]["key"])
    assert stored_remaining["score"] is None

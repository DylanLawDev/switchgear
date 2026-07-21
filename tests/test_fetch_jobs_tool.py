from switchgear.config import Settings
from switchgear.jobs.model import make_job
from switchgear.storage.memory import MemoryStorage
from switchgear.tools.fetch_jobs import DEFAULT_WATCHLIST, make_fetch_jobs_tool

S = Settings(_env_file=None)


def _job(**kwargs) -> dict:
    defaults = dict(
        url="https://boards.greenhouse.io/acme/jobs/1",
        title="Software Engineer",
        company="Acme",
        source="greenhouse",
    )
    defaults.update(kwargs)
    return make_job(**defaults)


def _stub(jobs=None, errors=None, expected_watchlist=None):
    jobs = jobs if jobs is not None else []
    errors = errors if errors is not None else []

    async def fetch_all(watchlist, settings):
        if expected_watchlist is not None:
            assert watchlist == expected_watchlist
        assert settings is S
        return {"jobs": jobs, "errors": errors}

    return fetch_all


async def test_seeds_default_watchlist_and_returns_fetched_jobs_as_new():
    storage = MemoryStorage()
    job = _job()
    tool = make_fetch_jobs_tool(
        S, storage, fetch_all=_stub([job], expected_watchlist=DEFAULT_WATCHLIST)
    )

    result = await tool.handler()

    assert result["new_count"] == 1
    assert result["seen_count"] == 0
    assert result["errors"] == []
    assert result["new"] == [{
        "key": job["key"],
        "title": job["title"],
        "company": job["company"],
        "location": job["location"],
        "score": None,
        "url": job["url"],
        "source": job["source"],
    }]

    persisted_watchlist = await storage.get("settings", "watchlist")
    assert persisted_watchlist == DEFAULT_WATCHLIST

    stored_job = await storage.get("jobs", job["key"])
    assert stored_job == job


async def test_second_call_with_same_job_is_fully_deduped():
    storage = MemoryStorage()
    job = _job()

    tool = make_fetch_jobs_tool(S, storage, fetch_all=_stub([job]))
    await tool.handler()

    tool2 = make_fetch_jobs_tool(S, storage, fetch_all=_stub([job]))
    result = await tool2.handler()

    assert result["new_count"] == 0
    assert result["seen_count"] == 1
    assert result["new"] == []


async def test_fuzzy_dedupe_same_company_and_title_different_url():
    storage = MemoryStorage()
    first = _job(url="https://boards.greenhouse.io/acme/jobs/1")
    tool = make_fetch_jobs_tool(S, storage, fetch_all=_stub([first]))
    await tool.handler()

    # A different URL (different key/source) but same company+title must fuzzy-dedupe.
    duplicate = _job(url="https://jobs.lever.co/acme/some-other-posting-id")
    assert duplicate["key"] != first["key"]

    tool2 = make_fetch_jobs_tool(S, storage, fetch_all=_stub([duplicate]))
    result = await tool2.handler()

    assert result["new_count"] == 0
    assert result["seen_count"] == 1

    stored_first = await storage.get("jobs", first["key"])
    assert stored_first == first
    assert await storage.get("jobs", duplicate["key"]) is None


async def test_identical_jobs_within_one_batch_insert_once():
    storage = MemoryStorage()
    job = _job()
    same_company_title = _job(url="https://jobs.lever.co/acme/duplicate-in-batch")
    assert same_company_title["key"] != job["key"]

    tool = make_fetch_jobs_tool(S, storage, fetch_all=_stub([job, same_company_title]))
    result = await tool.handler()

    assert result["new_count"] == 1
    assert result["seen_count"] == 1
    assert len(result["new"]) == 1
    assert result["new"][0]["key"] == job["key"]


async def test_errors_from_fetch_all_pass_through():
    storage = MemoryStorage()
    errors = [{"source": "greenhouse:acme", "error": "boom"}]
    tool = make_fetch_jobs_tool(S, storage, fetch_all=_stub([], errors=errors))

    result = await tool.handler()

    assert result["errors"] == errors
    assert result["new_count"] == 0
    assert result["seen_count"] == 0


async def test_custom_watchlist_already_in_storage_is_used():
    storage = MemoryStorage()
    custom = {"companies": [{"slug": "acme", "ats": "greenhouse"}], "feeds": [], "queries": []}
    await storage.put("settings", "watchlist", custom)

    tool = make_fetch_jobs_tool(S, storage, fetch_all=_stub([], expected_watchlist=custom))
    result = await tool.handler()

    assert result["new_count"] == 0
    # watchlist in storage is untouched (still the custom one, not overwritten by default)
    assert await storage.get("settings", "watchlist") == custom

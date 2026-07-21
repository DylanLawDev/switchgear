import httpx
import respx

from switchgear.config import Settings
from switchgear.jobs.fetchers import (
    fetch_all,
    fetch_ashby,
    fetch_greenhouse,
    fetch_jsearch,
    fetch_lever,
    fetch_remoteok,
    fetch_remotive,
)

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/acme"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/acme"
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
REMOTEOK_URL = "https://remoteok.com/api"
JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


# --- per-source happy path ---------------------------------------------------


@respx.mock
async def test_fetch_greenhouse_calls_expected_url_and_normalizes():
    respx.get(GREENHOUSE_URL).respond(json={
        "jobs": [{
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            "title": "Engineer",
            "location": {"name": "Remote"},
            "content": "Build stuff",
        }]
    })
    async with httpx.AsyncClient() as client:
        jobs = await fetch_greenhouse(client, "acme")
    assert len(jobs) == 1
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["source"] == "greenhouse"
    request = respx.calls.last.request
    assert request.url.path == "/v1/boards/acme/jobs"
    assert request.url.params["content"] == "true"


@respx.mock
async def test_fetch_lever_calls_expected_url_and_normalizes():
    respx.get(LEVER_URL).respond(json=[{
        "hostedUrl": "https://jobs.lever.co/acme/1",
        "text": "Backend Engineer",
        "categories": {"location": "Remote"},
        "descriptionPlain": "Do backend things.",
    }])
    async with httpx.AsyncClient() as client:
        jobs = await fetch_lever(client, "acme")
    assert len(jobs) == 1
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["source"] == "lever"
    request = respx.calls.last.request
    assert request.url.path == "/v0/postings/acme"
    assert request.url.params["mode"] == "json"


@respx.mock
async def test_fetch_ashby_calls_expected_url_and_normalizes():
    respx.get(ASHBY_URL).respond(json={
        "jobs": [{
            "jobUrl": "https://jobs.ashbyhq.com/acme/1",
            "title": "Product Manager",
            "location": "NYC",
            "isRemote": False,
            "descriptionHtml": "Own the roadmap.",
        }]
    })
    async with httpx.AsyncClient() as client:
        jobs = await fetch_ashby(client, "acme")
    assert len(jobs) == 1
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["source"] == "ashby"
    request = respx.calls.last.request
    assert request.url.path == "/posting-api/job-board/acme"


@respx.mock
async def test_fetch_remotive_calls_expected_url_and_normalizes():
    respx.get(REMOTIVE_URL).respond(json={
        "jobs": [{
            "url": "https://remotive.com/remote-jobs/1",
            "title": "Data Scientist",
            "company_name": "Remoteco",
            "candidate_required_location": "Worldwide",
            "salary": "$100k",
            "description": "Crunch numbers.",
        }]
    })
    async with httpx.AsyncClient() as client:
        jobs = await fetch_remotive(client, "python")
    assert len(jobs) == 1
    assert jobs[0]["source"] == "remotive"
    request = respx.calls.last.request
    assert request.url.path == "/api/remote-jobs"
    assert request.url.params["search"] == "python"


@respx.mock
async def test_fetch_remoteok_calls_expected_url_and_normalizes():
    respx.get(REMOTEOK_URL).respond(json=[
        {"legal": "notice"},
        {
            "position": "Frontend Engineer",
            "company": "Okco",
            "location": "Anywhere",
            "url": "https://remoteok.com/remote-jobs/1",
            "description": "Build UI.",
        },
    ])
    async with httpx.AsyncClient() as client:
        jobs = await fetch_remoteok(client)
    assert len(jobs) == 1
    assert jobs[0]["source"] == "remoteok"
    request = respx.calls.last.request
    assert request.url.path == "/api"


@respx.mock
async def test_fetch_jsearch_calls_expected_url_headers_and_normalizes():
    respx.get(JSEARCH_URL).respond(json={
        "data": [{
            "job_title": "DevOps Engineer",
            "employer_name": "Cloudify",
            "job_apply_link": "https://jsearch.example.com/jobs/1",
            "job_is_remote": True,
            "job_description": "Automate everything.",
        }]
    })
    async with httpx.AsyncClient() as client:
        jobs = await fetch_jsearch(client, "python", "test-api-key")
    assert len(jobs) == 1
    assert jobs[0]["source"] == "jsearch"
    request = respx.calls.last.request
    assert request.url.path == "/search"
    assert request.url.params["query"] == "python"
    assert request.url.params["num_pages"] == "1"
    assert request.headers["X-RapidAPI-Key"] == "test-api-key"
    assert request.headers["X-RapidAPI-Host"] == "jsearch.p.rapidapi.com"


# --- per-source raises on HTTP error -----------------------------------------


@respx.mock
async def test_fetch_greenhouse_raises_on_http_error():
    respx.get(GREENHOUSE_URL).respond(500)
    async with httpx.AsyncClient() as client:
        try:
            await fetch_greenhouse(client, "acme")
            raised = False
        except httpx.HTTPStatusError:
            raised = True
    assert raised


# --- fetch_all: isolation invariant ------------------------------------------


@respx.mock
async def test_fetch_all_isolates_failing_source_and_keeps_others():
    respx.get(GREENHOUSE_URL).respond(500)
    respx.get(REMOTIVE_URL).respond(json={
        "jobs": [{
            "url": "https://remotive.com/remote-jobs/1",
            "title": "Data Scientist",
            "company_name": "Remoteco",
            "candidate_required_location": "Worldwide",
            "description": "Crunch numbers.",
        }]
    })
    watchlist = {
        "companies": [{"slug": "acme", "ats": "greenhouse"}],
        "feeds": ["remotive"],
        "queries": ["python"],
    }
    result = await fetch_all(watchlist, _settings())
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["source"] == "remotive"
    assert len(result["errors"]) == 1
    assert result["errors"][0]["source"] == "greenhouse:acme"
    assert "error" in result["errors"][0]


@respx.mock
async def test_fetch_all_malformed_company_entry_is_isolated():
    respx.get(REMOTIVE_URL).respond(json={
        "jobs": [{
            "url": "https://remotive.com/remote-jobs/1",
            "title": "Data Scientist",
            "company_name": "Remoteco",
            "candidate_required_location": "Worldwide",
            "description": "Crunch numbers.",
        }]
    })
    watchlist = {
        "companies": [{"slug": "acme"}],
        "feeds": ["remotive"],
        "queries": ["python"],
    }
    result = await fetch_all(watchlist, _settings())
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["source"] == "remotive"
    assert len(result["errors"]) == 1
    assert result["errors"][0]["source"] == "watchlist:acme"
    assert "error" in result["errors"][0]


@respx.mock
async def test_fetch_all_unknown_ats_reports_error_and_continues():
    respx.get(REMOTEOK_URL).respond(json=[{
        "position": "Frontend Engineer",
        "company": "Okco",
        "url": "https://remoteok.com/remote-jobs/1",
        "description": "Build UI.",
    }])
    watchlist = {
        "companies": [{"slug": "mystery", "ats": "bogus"}],
        "feeds": ["remoteok"],
        "queries": [],
    }
    result = await fetch_all(watchlist, _settings())
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["source"] == "remoteok"
    assert len(result["errors"]) == 1
    assert result["errors"][0]["source"] == "bogus:mystery"


# --- fetch_all: jsearch gating -------------------------------------------------


@respx.mock
async def test_fetch_all_skips_jsearch_when_api_key_empty():
    watchlist = {"companies": [], "feeds": [], "queries": ["python"]}
    result = await fetch_all(watchlist, _settings(jsearch_api_key=""))
    assert result == {"jobs": [], "errors": []}
    assert not respx.calls.called


@respx.mock
async def test_fetch_all_calls_jsearch_with_key_when_set():
    respx.get(JSEARCH_URL).respond(json={
        "data": [{
            "job_title": "DevOps Engineer",
            "employer_name": "Cloudify",
            "job_apply_link": "https://jsearch.example.com/jobs/1",
            "job_is_remote": True,
            "job_description": "Automate everything.",
        }]
    })
    watchlist = {"companies": [], "feeds": [], "queries": ["python"]}
    result = await fetch_all(watchlist, _settings(jsearch_api_key="rapid-key"))
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["source"] == "jsearch"
    request = respx.calls.last.request
    assert request.headers["X-RapidAPI-Key"] == "rapid-key"
    assert not result["errors"]

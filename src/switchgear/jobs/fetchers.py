import httpx

from switchgear.config import Settings
from switchgear.jobs.model import (
    normalize_ashby,
    normalize_greenhouse,
    normalize_jsearch,
    normalize_lever,
    normalize_remoteok,
    normalize_remotive,
)

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{org}"
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
REMOTEOK_URL = "https://remoteok.com/api"
JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"


async def fetch_greenhouse(client: httpx.AsyncClient, slug: str) -> list[dict]:
    resp = await client.get(GREENHOUSE_URL.format(slug=slug), params={"content": "true"})
    resp.raise_for_status()
    return normalize_greenhouse(resp.json(), slug.title())


async def fetch_lever(client: httpx.AsyncClient, slug: str) -> list[dict]:
    resp = await client.get(LEVER_URL.format(slug=slug), params={"mode": "json"})
    resp.raise_for_status()
    return normalize_lever(resp.json(), slug.title())


async def fetch_ashby(client: httpx.AsyncClient, org: str) -> list[dict]:
    resp = await client.get(ASHBY_URL.format(org=org))
    resp.raise_for_status()
    return normalize_ashby(resp.json(), org.title())


async def fetch_remotive(client: httpx.AsyncClient, query: str) -> list[dict]:
    resp = await client.get(REMOTIVE_URL, params={"search": query})
    resp.raise_for_status()
    return normalize_remotive(resp.json())


async def fetch_remoteok(client: httpx.AsyncClient) -> list[dict]:
    resp = await client.get(REMOTEOK_URL)
    resp.raise_for_status()
    return normalize_remoteok(resp.json())


async def fetch_jsearch(client: httpx.AsyncClient, query: str, api_key: str) -> list[dict]:
    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
    resp = await client.get(
        JSEARCH_URL, params={"query": query, "num_pages": 1}, headers=headers
    )
    resp.raise_for_status()
    return normalize_jsearch(resp.json())


_ATS_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}


async def fetch_all(watchlist: dict, settings: Settings) -> dict:
    jobs: list[dict] = []
    errors: list[dict] = []

    async with httpx.AsyncClient(timeout=30) as client:
        for company in watchlist.get("companies", []):
            slug = company.get("slug")
            ats = company.get("ats")
            if not slug or not ats:
                errors.append({
                    "source": f"watchlist:{slug or '?'}",
                    "error": "company entry needs slug and ats",
                })
                continue
            fetcher = _ATS_FETCHERS.get(ats)
            if fetcher is None:
                errors.append({"source": f"{ats}:{slug}", "error": f"unknown ats: {ats}"})
                continue
            try:
                jobs.extend(await fetcher(client, slug))
            except Exception as exc:
                errors.append({"source": f"{ats}:{slug}", "error": str(exc)})

        feeds = watchlist.get("feeds", [])
        queries = watchlist.get("queries", [])

        if "remotive" in feeds:
            for query in queries:
                try:
                    jobs.extend(await fetch_remotive(client, query))
                except Exception as exc:
                    errors.append({"source": "remotive", "error": str(exc)})

        if "remoteok" in feeds:
            try:
                jobs.extend(await fetch_remoteok(client))
            except Exception as exc:
                errors.append({"source": "remoteok", "error": str(exc)})

        if settings.jsearch_api_key:
            for query in queries:
                try:
                    jobs.extend(
                        await fetch_jsearch(client, query, settings.jsearch_api_key)
                    )
                except Exception as exc:
                    errors.append({"source": "jsearch", "error": str(exc)})

    return {"jobs": jobs, "errors": errors}

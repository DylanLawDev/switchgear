from switchgear.config import Settings
from switchgear.jobs import fetchers
from switchgear.jobs.model import fuzzy_key
from switchgear.storage.base import Storage
from switchgear.tools.base import Tool

DEFAULT_WATCHLIST = {
    "companies": [],
    "feeds": ["remotive", "remoteok"],
    "queries": ["software engineer"],
}

_SUMMARY_FIELDS = ("key", "title", "company", "location", "url", "source")


def make_fetch_jobs_tool(
    settings: Settings, storage: Storage, fetch_all=fetchers.fetch_all
) -> Tool:
    async def _fetch_jobs() -> dict:
        watchlist = await storage.get("settings", "watchlist")
        if watchlist is None:
            watchlist = DEFAULT_WATCHLIST
            await storage.put("settings", "watchlist", watchlist)

        result = await fetch_all(watchlist, settings)
        fetched_jobs = result.get("jobs", [])
        errors = result.get("errors", [])

        existing_jobs = await storage.query("jobs")
        existing_keys = {job["key"] for job in existing_jobs}
        existing_fuzzy = {fuzzy_key(job["company"], job["title"]) for job in existing_jobs}

        batch_keys: set[str] = set()
        batch_fuzzy: set[str] = set()
        new_jobs = []
        seen_count = 0

        for job in fetched_jobs:
            key = job["key"]
            fkey = fuzzy_key(job["company"], job["title"])
            if (
                key in existing_keys
                or fkey in existing_fuzzy
                or key in batch_keys
                or fkey in batch_fuzzy
            ):
                seen_count += 1
                continue
            batch_keys.add(key)
            batch_fuzzy.add(fkey)
            new_jobs.append(job)

        for job in new_jobs:
            await storage.put("jobs", job["key"], job)

        return {
            "new": [{**{field: job[field] for field in _SUMMARY_FIELDS}, "score": None}
                    for job in new_jobs],
            "new_count": len(new_jobs),
            "seen_count": seen_count,
            "errors": errors,
        }

    return Tool(
        name="fetch_jobs",
        description=(
            "Fetch new job postings from the configured watchlist (ATS companies, "
            "feeds, and search queries), deduping against previously seen jobs and "
            "persisting new ones."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_fetch_jobs,
    )

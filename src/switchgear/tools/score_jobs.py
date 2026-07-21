import time

from switchgear.config import Settings
from switchgear.gateway import Gateway
from switchgear.jobs.scoring import BATCH_SIZE, DEFAULT_CAREER_SUMMARY, score_batch
from switchgear.storage.base import Storage
from switchgear.tools.base import Tool

_SUMMARY_FIELDS = ("key", "title", "company", "url", "location", "score", "rationale")


def make_score_jobs_tool(settings: Settings, storage: Storage, gateway: Gateway) -> Tool:
    async def _score_jobs(limit: int = 50) -> dict:
        career_summary = await storage.get("settings", "career_summary")
        if career_summary is None:
            career_summary = DEFAULT_CAREER_SUMMARY
            await storage.put("settings", "career_summary", career_summary)

        all_jobs = await storage.query("jobs")
        unscored = [job for job in all_jobs if job.get("score") is None][:limit]

        scored = []
        errors: list[str] = []
        for i in range(0, len(unscored), BATCH_SIZE):
            batch = unscored[i:i + BATCH_SIZE]
            try:
                results = await score_batch(gateway, career_summary, batch)
            except Exception as e:
                errors.append(str(e))
                continue

            by_key = {job["key"]: job for job in batch}
            for result in results:
                job = by_key.get(result["key"])
                if job is None:
                    continue
                job["score"] = result["score"]
                job["rationale"] = result["rationale"]
                job["scored_at"] = time.time()
                job.pop("_id", None)
                await storage.put("jobs", job["key"], job)
                scored.append({field: job[field] for field in _SUMMARY_FIELDS})

        scored.sort(key=lambda job: job["score"], reverse=True)

        return {
            "scored": scored,
            "scored_count": len(scored),
            "errors": errors,
        }

    return Tool(
        name="score_jobs",
        description=(
            "Score unscored jobs against the stored career summary using the bulk "
            "LLM tier, in batches, persisting scores and rationales back to storage."
        ),
        parameters={"type": "object", "properties": {
            "limit": {"type": "integer", "default": 50}}, "required": []},
        handler=_score_jobs,
    )

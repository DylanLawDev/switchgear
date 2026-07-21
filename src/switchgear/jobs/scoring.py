import json
import re

BATCH_SIZE = 10

DEFAULT_CAREER_SUMMARY = (
    "Software engineer. Edit the career_summary key in the settings collection "
    "(or ask the agent) so scoring reflects your real background."
)

_DESCRIPTION_LIMIT = 3000
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class ScoringError(Exception):
    pass


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    return match.group(1).strip() if match else stripped


def _build_messages(career_summary: str, jobs: list[dict]) -> list[dict]:
    lines = [
        f"Career summary: {career_summary}",
        "",
        "Score each job posting below from 0 to 100 for how well it fits the "
        "career summary above.",
        "Reply with ONLY a JSON array and no other text, markdown, or code fence:",
        '[{"key": "<key>", "score": <0-100 integer>, "rationale": "<one sentence>"}]',
        "",
        "Jobs:",
    ]
    for job in jobs:
        description = (job.get("description") or "")[:_DESCRIPTION_LIMIT]
        lines.append(
            f"- key: {job['key']}\n"
            f"  title: {job.get('title', '')}\n"
            f"  company: {job.get('company', '')}\n"
            f"  location: {job.get('location', '')}\n"
            f"  description: {description}"
        )
    return [{"role": "user", "content": "\n".join(lines)}]


async def score_batch(gateway, career_summary: str, jobs: list[dict]) -> list[dict]:
    messages = _build_messages(career_summary, jobs)
    completion = await gateway.complete("bulk", messages)
    content = completion.message.get("content") or ""

    try:
        data = json.loads(_strip_fence(content))
    except json.JSONDecodeError as e:
        raise ScoringError(f"could not parse scoring response as JSON: {e}") from e

    if not isinstance(data, list):
        raise ScoringError("scoring response was not a JSON array")

    valid_keys = {job["key"] for job in jobs}
    results = []
    for entry in data:
        if not isinstance(entry, dict) or entry.get("key") not in valid_keys:
            continue
        try:
            score = int(entry.get("score", 0))
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(100, score))
        rationale = str(entry.get("rationale", ""))
        results.append({"key": entry["key"], "score": score, "rationale": rationale})
    return results

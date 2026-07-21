import hashlib
import html
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")
_DROPPED_PARAM_PREFIX = "utm_"
_DROPPED_PARAMS = {"ref", "source"}

MAX_DESCRIPTION_LENGTH = 20_000


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    kept_params = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _DROPPED_PARAMS and not key.startswith(_DROPPED_PARAM_PREFIX)
    ]
    query = urlencode(kept_params)
    return urlunsplit((scheme, netloc, path, query, ""))


def job_key(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()


def fuzzy_key(company: str, title: str) -> str:
    raw = f"{company}:{title}".lower()
    return _NON_ALNUM_RE.sub("", raw)


def strip_html(text: str) -> str:
    if not text:
        return ""
    no_tags = _TAG_RE.sub(" ", text)
    unescaped = html.unescape(no_tags)
    return _WS_RE.sub(" ", unescaped).strip()


def make_job(
    *,
    url: str,
    title: str,
    company: str,
    location: str = "",
    remote: bool = False,
    comp: str = "",
    description: str = "",
    source: str,
) -> dict:
    stripped_description = strip_html(description)[:MAX_DESCRIPTION_LENGTH]
    return {
        "key": job_key(url),
        "url": url,
        "title": title,
        "company": company,
        "location": location,
        "remote": remote,
        "comp": comp,
        "description": stripped_description,
        "source": source,
        "first_seen": time.time(),
        "score": None,
        "rationale": None,
        "scored_at": None,
    }


def normalize_greenhouse(data: dict, company: str) -> list[dict]:
    jobs = []
    for entry in data.get("jobs", []):
        url = entry.get("absolute_url")
        title = entry.get("title")
        if not url or not title:
            continue
        location = (entry.get("location") or {}).get("name") or ""
        jobs.append(
            make_job(
                url=url,
                title=title,
                company=company,
                location=location,
                description=entry.get("content", ""),
                source="greenhouse",
            )
        )
    return jobs


def normalize_lever(data: list, company: str) -> list[dict]:
    jobs = []
    for entry in data:
        url = entry.get("hostedUrl")
        title = entry.get("text")
        if not url or not title:
            continue
        categories = entry.get("categories") or {}
        location = categories.get("location") or ""
        jobs.append(
            make_job(
                url=url,
                title=title,
                company=company,
                location=location,
                remote="remote" in location.lower(),
                description=entry.get("descriptionPlain", ""),
                source="lever",
            )
        )
    return jobs


def normalize_ashby(data: dict, company: str) -> list[dict]:
    jobs = []
    for entry in data.get("jobs", []):
        url = entry.get("jobUrl")
        title = entry.get("title")
        if not url or not title:
            continue
        jobs.append(
            make_job(
                url=url,
                title=title,
                company=company,
                location=entry.get("location") or "",
                remote=bool(entry.get("isRemote")),
                comp=entry.get("compensation") or "",
                description=entry.get("descriptionHtml", ""),
                source="ashby",
            )
        )
    return jobs


def normalize_remotive(data: dict) -> list[dict]:
    jobs = []
    for entry in data.get("jobs", []):
        url = entry.get("url")
        title = entry.get("title")
        if not url or not title:
            continue
        jobs.append(
            make_job(
                url=url,
                title=title,
                company=entry.get("company_name", ""),
                location=entry.get("candidate_required_location") or "",
                remote=True,
                comp=entry.get("salary") or "",
                description=entry.get("description", ""),
                source="remotive",
            )
        )
    return jobs


def normalize_remoteok(data: list) -> list[dict]:
    jobs = []
    for entry in data:
        if "position" not in entry:
            continue
        url = entry.get("url")
        title = entry.get("position")
        if not url or not title:
            continue
        jobs.append(
            make_job(
                url=url,
                title=title,
                company=entry.get("company", ""),
                location=entry.get("location") or "",
                remote=True,
                description=entry.get("description", ""),
                source="remoteok",
            )
        )
    return jobs


def normalize_jsearch(data: dict) -> list[dict]:
    jobs = []
    for entry in data.get("data", []):
        url = entry.get("job_apply_link")
        title = entry.get("job_title")
        if not url or not title:
            continue
        city = entry.get("job_city") or ""
        country = entry.get("job_country") or ""
        location = ", ".join(part for part in (city, country) if part)
        min_salary = entry.get("job_min_salary")
        max_salary = entry.get("job_max_salary")
        has_both_salaries = min_salary is not None and max_salary is not None
        comp = f"{min_salary}-{max_salary}" if has_both_salaries else ""
        jobs.append(
            make_job(
                url=url,
                title=title,
                company=entry.get("employer_name", ""),
                location=location,
                remote=bool(entry.get("job_is_remote")),
                comp=comp,
                description=entry.get("job_description", ""),
                source="jsearch",
            )
        )
    return jobs

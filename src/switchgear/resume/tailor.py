import json
import re

from switchgear.career.bank import CareerBank

_DESCRIPTION_LIMIT = 6000
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

_SYSTEM_PROMPT = (
    "You are tailoring a resume from a career bank of grounded facts.\n"
    "Select and arrange only — never invent new claims, numbers, or technologies.\n"
    "Every bullet you produce must cite a fact_id taken from the fact list given below; "
    "do not use a fact_id that is not in that list.\n"
    "A bullet's text may lightly rephrase the wording of its source fact, but it must not "
    "add any new claim, number, or technology beyond what is in the source fact. If you do "
    "not want to rephrase a fact, omit the text field (or set it to null) and the source "
    "text will be used verbatim.\n"
    "The summary may only draw on the candidate profile and the facts you selected — do not "
    "introduce any other information.\n"
    "Reply with ONLY JSON matching the exact shape shown below. No markdown, no code fences, "
    "no commentary, no other text."
)

_SELECTION_SHAPE = {
    "summary": "one short paragraph",
    "sections": [
        {
            "heading": "Experience",
            "entries": [
                {
                    "company": "Example Corp",
                    "title": "Software Engineer",
                    "dates": "2022-01 - present",
                    "bullets": [{"fact_id": "example-metrics", "text": "optional light rephrase"}],
                }
            ],
        },
        {
            "heading": "Skills",
            "entries": [{"bullets": [{"fact_id": "...", "text": None}]}],
        },
    ],
}


class TailorError(Exception):
    pass


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    return match.group(1).strip() if match else stripped


def build_tailor_messages(job: dict, bank: CareerBank) -> list[dict]:
    description = (job.get("description") or "")[:_DESCRIPTION_LIMIT]
    facts = [
        {
            "id": fid,
            "text": bank.facts[fid]["text"],
            "skills": bank.facts[fid]["skills"],
            "metric": bank.facts[fid]["metric"],
        }
        for fid in sorted(bank.fact_ids)
    ]

    user_lines = [
        f"Job title: {job.get('title', '')}",
        f"Company: {job.get('company', '')}",
        f"Job description:\n{description}",
        "",
        f"Candidate profile:\n{json.dumps(bank.profile)}",
        "",
        f"Skills inventory:\n{json.dumps(bank.skills)}",
        "",
        "Available facts (every bullet must cite one of these fact ids):",
        json.dumps(facts, indent=2),
        "",
        "Reply with ONLY JSON matching exactly this shape:",
        json.dumps(_SELECTION_SHAPE, indent=2),
    ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_lines)},
    ]


def parse_selection(content: str) -> dict:
    try:
        data = json.loads(_strip_fence(content))
    except json.JSONDecodeError as e:
        raise TailorError(f"could not parse selection response as JSON: {e}") from None

    if not isinstance(data, dict):
        raise TailorError("selection response was not a JSON object")
    if not isinstance(data.get("summary"), str):
        raise TailorError("selection response missing required string field 'summary'")
    if not isinstance(data.get("sections"), list):
        raise TailorError("selection response missing required list field 'sections'")

    for i, section in enumerate(data["sections"]):
        if not isinstance(section, dict):
            raise TailorError(
                f"selection section {i} is not a JSON object (got {type(section).__name__})"
            )
        entries = section.get("entries", [])
        if not isinstance(entries, list):
            raise TailorError(
                f"selection section {i} has non-list 'entries' (got {type(entries).__name__})"
            )
        for j, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise TailorError(
                    f"selection section {i} entry {j} is not a JSON object "
                    f"(got {type(entry).__name__})"
                )
            bullets = entry.get("bullets", [])
            if not isinstance(bullets, list):
                raise TailorError(
                    f"selection section {i} entry {j} has non-list 'bullets' "
                    f"(got {type(bullets).__name__})"
                )
            for k, bullet in enumerate(bullets):
                if not isinstance(bullet, dict):
                    raise TailorError(
                        f"selection section {i} entry {j} bullet {k} is not a JSON object "
                        f"(got {type(bullet).__name__})"
                    )

    return data


def validate_selection(selection: dict, bank: CareerBank) -> dict:
    bad_fact_ids: list = []
    bad_texts: list = []

    for section in selection.get("sections", []):
        for entry in section.get("entries", []):
            bullets = entry.get("bullets", [])
            for i, bullet in enumerate(bullets):
                fid = bullet.get("fact_id")
                if not isinstance(fid, str) or fid not in bank.fact_ids:
                    bad_fact_ids.append(fid)
                    continue
                text = bullet.get("text")
                if text is not None and not isinstance(text, str):
                    bad_texts.append((fid, type(text).__name__))
                    continue
                source = bank.facts[fid]["text"]
                rephrased = bool(text) and text.split() != source.split()
                bullets[i] = {
                    "fact_id": fid,
                    "text": text,
                    "source_text": source,
                    "rephrased": rephrased,
                }

    if bad_fact_ids or bad_texts:
        messages = []
        if bad_fact_ids:
            messages.append(f"selection cites unknown or missing fact_id(s): {bad_fact_ids}")
        if bad_texts:
            messages.append(
                "selection has non-string bullet text (expected str or null) for "
                f"fact_id(s)/type(s): {bad_texts}"
            )
        raise TailorError("; ".join(messages))

    for section in selection.get("sections", []):
        for entry in section.get("entries", []):
            _ground_entry_header(entry, bank)

    return selection


def _ground_entry_header(entry: dict, bank: CareerBank) -> None:
    """Ground (or strip) an entry's company/title/dates header against the bank.

    Entries that provide a company or title are treated as experience entries:
    every cited fact must belong to the same (company, title) experience, the
    provided company/title must match that experience (case-insensitively), and
    the header is then overwritten with the bank's values so headers can never
    diverge from the grounded facts. Entries with neither field (e.g. a Skills
    section) are left alone except that any LLM-supplied 'dates' is stripped,
    since there is no fact context to ground it against.
    """
    has_company = bool(entry.get("company"))
    has_title = bool(entry.get("title"))

    if not has_company and not has_title:
        if "dates" in entry:
            entry["dates"] = None
        return

    bullets = entry.get("bullets") or []
    if not bullets:
        return

    contexts: dict[tuple, dict] = {}
    for bullet in bullets:
        fact = bank.facts[bullet["fact_id"]]
        key = (fact["company"].strip().lower(), fact["title"].strip().lower())
        contexts.setdefault(key, fact)

    if len(contexts) > 1:
        spans = ", ".join(
            f"{fact['company']} / {fact['title']}"
            for fact in sorted(contexts.values(), key=lambda f: (f["company"], f["title"]))
        )
        raise TailorError(
            "selection entry cites facts spanning multiple experiences "
            f"({spans}); an entry with a company/title header must cite facts "
            "from exactly one experience"
        )

    context_fact = next(iter(contexts.values()))
    bank_company = context_fact["company"]
    bank_title = context_fact["title"]

    if has_company and str(entry["company"]).strip().lower() != bank_company.strip().lower():
        raise TailorError(
            f"selection entry company {entry['company']!r} does not match the "
            f"cited facts' experience company {bank_company!r}"
        )
    if has_title and str(entry["title"]).strip().lower() != bank_title.strip().lower():
        raise TailorError(
            f"selection entry title {entry['title']!r} does not match the "
            f"cited facts' experience title {bank_title!r}"
        )

    entry["company"] = bank_company
    entry["title"] = bank_title
    start = context_fact.get("start")
    end = context_fact.get("end")
    entry["dates"] = f"{start} – {end}" if start and end else None


async def tailor_selection(gateway, job: dict, bank: CareerBank) -> dict:
    messages = build_tailor_messages(job, bank)
    completion = await gateway.complete("writing", messages)
    content = completion.message.get("content") or ""
    selection = parse_selection(content)
    return validate_selection(selection, bank)

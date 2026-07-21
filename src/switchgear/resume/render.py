"""Deterministic ATS-safe resume renderer and JD keyword coverage report.

Pure functions only: no LLM calls, no randomness, no timestamps. Every value
interpolated into HTML is escaped via ``html.escape``.
"""

import html
import re

from switchgear.career.bank import CareerBank


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _contact_line(profile: dict) -> str:
    parts = []
    for key in ("email", "phone", "location"):
        value = profile.get(key)
        if value:
            parts.append(str(value))
    for link in profile.get("links") or []:
        if link:
            parts.append(str(link))
    return " · ".join(_esc(p) for p in parts)


def _entry_header(entry: dict) -> str:
    parts = []
    for key in ("company", "title", "dates"):
        value = entry.get(key)
        if value:
            parts.append(str(value))
    return " — ".join(_esc(p) for p in parts)


def _bullet_text(bullet: dict) -> str:
    text = bullet.get("text")
    if text is None:
        text = bullet.get("source_text")
    return _esc(text or "")


def _render_education(profile: dict) -> str:
    education = profile.get("education") or []
    if not education:
        return ""
    lines = ["<h2>Education</h2>"]
    for item in education:
        parts = []
        for key in ("school", "degree", "year"):
            value = item.get(key)
            if value:
                parts.append(str(value))
        line = " — ".join(_esc(p) for p in parts)
        if line:
            lines.append(f"<p>{line}</p>")
    return "\n".join(lines)


def render_html(profile: dict, selection: dict, *, title: str = "Resume") -> str:
    """Render a single-column, ATS-safe HTML resume. Pure function, no I/O."""
    lines = [
        "<!doctype html>",
        "<html lang=\"en\">",
        "<head>",
        f"<meta charset=\"utf-8\"><title>{_esc(title)}</title>",
        "<style>body{font-family:Arial,Helvetica,sans-serif;}</style>",
        "</head>",
        "<body>",
        f"<h1>{_esc(profile.get('name', ''))}</h1>",
    ]

    contact = _contact_line(profile)
    if contact:
        lines.append(f"<p>{contact}</p>")

    summary = selection.get("summary")
    if summary:
        lines.append(f"<p>{_esc(summary)}</p>")

    for section in selection.get("sections") or []:
        heading = section.get("heading", "")
        lines.append(f"<h2>{_esc(heading)}</h2>")
        for entry in section.get("entries") or []:
            header = _entry_header(entry)
            if header:
                lines.append(f"<p>{header}</p>")
            bullets = entry.get("bullets") or []
            if bullets:
                lines.append("<ul>")
                for bullet in bullets:
                    lines.append(f"<li>{_bullet_text(bullet)}</li>")
                lines.append("</ul>")

    education_html = _render_education(profile)
    if education_html:
        lines.append(education_html)

    lines.append("</body>")
    lines.append("</html>")
    return "\n".join(lines)


def _skill_universe(bank: CareerBank) -> list[str]:
    seen: dict[str, str] = {}
    for skill in bank.skills:
        name = skill.get("name")
        if name and name.lower() not in seen:
            seen[name.lower()] = name
    for fact in bank.facts.values():
        for tag in fact.get("skills") or []:
            if tag.lower() not in seen:
                seen[tag.lower()] = tag
    return sorted(seen.values(), key=str.lower)


def _term_pattern(term: str) -> re.Pattern:
    """Case-insensitive whole-term matcher that works for punctuation-heavy terms.

    ``\\b`` word boundaries don't fire next to non-word characters, so terms like
    "C++", "C#", or ".NET" never match with a plain ``\\bterm\\b`` pattern (there is
    no boundary between "+" and "+", or between a leading "." and "N"). Lookarounds
    that just forbid an adjacent word character on either side work for both
    word-like and punctuation-heavy terms alike.
    """
    return re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)


def extract_jd_terms(jd_text: str, bank: CareerBank) -> list[str]:
    """Bank skill terms that appear (case-insensitive, whole-term) in jd_text."""
    terms = []
    for term in _skill_universe(bank):
        if _term_pattern(term).search(jd_text):
            terms.append(term)
    return sorted(terms, key=str.lower)


def _selected_fact_ids(selection: dict) -> list[str]:
    fact_ids = []
    for section in selection.get("sections") or []:
        for entry in section.get("entries") or []:
            for bullet in entry.get("bullets") or []:
                fact_id = bullet.get("fact_id")
                if fact_id:
                    fact_ids.append(fact_id)
    return fact_ids


def _bullets_by_fact(selection: dict) -> dict:
    result = {}
    for section in selection.get("sections") or []:
        for entry in section.get("entries") or []:
            for bullet in entry.get("bullets") or []:
                fact_id = bullet.get("fact_id")
                if fact_id:
                    result[fact_id] = bullet
    return result


def keyword_report(jd_text: str, selection: dict, bank: CareerBank) -> dict:
    """Report which JD terms the selection covers. Selected facts only."""
    terms = extract_jd_terms(jd_text, bank)
    fact_ids = _selected_fact_ids(selection)
    bullets = _bullets_by_fact(selection)

    hit: list[str] = []
    missed: list[str] = []
    for term in terms:
        pattern = _term_pattern(term)
        covered = False
        for fact_id in fact_ids:
            fact = bank.facts.get(fact_id)
            if fact is None:
                continue
            if any(term.lower() == tag.lower() for tag in fact.get("skills") or []):
                covered = True
                break
            bullet = bullets.get(fact_id) or {}
            for text_field in ("text", "source_text"):
                text = bullet.get(text_field)
                if text and pattern.search(text):
                    covered = True
                    break
            if covered:
                break
        (hit if covered else missed).append(term)
    return {"hit": hit, "missed": missed}

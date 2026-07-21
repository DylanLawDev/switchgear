import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FACT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


class CareerBankError(Exception):
    pass


def _load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise CareerBankError(f"{path.name}: bad yaml: {e}") from None
    if not isinstance(data, dict):
        raise CareerBankError(f"{path.name}: content must be a mapping")
    return data


@dataclass
class CareerBank:
    profile: dict
    skills: list
    experiences: list
    facts: dict = field(default_factory=dict)
    fact_ids: set = field(default_factory=set)

    def summary_text(self) -> str:
        lines = []
        name = self.profile.get("name", "")
        headline = self.profile.get("headline", "")
        summary = self.profile.get("summary", "")
        header = " — ".join(p for p in (name, headline) if p)
        if header:
            lines.append(header)
        if summary:
            lines.append(str(summary).strip())
        if self.skills:
            lines.append(", ".join(f"{s['name']} ({s['years']}y)" for s in self.skills))
        for fid in sorted(self.fact_ids):
            fact = self.facts[fid]
            lines.append(f"{fact['company']} — {fact['title']}: {fact['text']}")
        return "\n".join(lines)


def _parse_fact(raw: dict, where: str, company: str, title: str,
                start, end, seen_ids: set) -> dict:
    if not isinstance(raw, dict):
        raise CareerBankError(f"{where}: each fact must be a mapping")
    fid = raw.get("id")
    if not fid or not FACT_ID_RE.match(str(fid)):
        raise CareerBankError(
            f"{where}: fact field 'id' is invalid: {fid!r} "
            "(must match ^[a-z0-9][a-z0-9-]{1,63}$)")
    fid = str(fid)
    if fid in seen_ids:
        raise CareerBankError(
            f"{where}: duplicate fact id '{fid}' (already used elsewhere)")
    text = raw.get("text")
    if not text or not str(text).strip():
        raise CareerBankError(f"{where}: fact '{fid}' missing required field 'text'")
    skills = raw.get("skills") or []
    if not isinstance(skills, list) or not all(
        isinstance(s, str) and s == s.lower() for s in skills
    ):
        raise CareerBankError(
            f"{where}: fact '{fid}' field 'skills' must be a list of lowercase strings")
    return {
        "id": fid,
        "text": str(text),
        "skills": skills,
        "metric": raw.get("metric"),
        "company": company,
        "title": title,
        # canonicalize: yaml resolves full ISO dates to datetime.date, but the
        # seeded career-bank json resource can only carry strings — coerce here
        # so file loading and resource round-trips produce identical facts
        "start": str(start) if start is not None else None,
        "end": str(end) if end is not None else None,
    }


def from_dict(data: dict) -> CareerBank:
    """Validate and assemble a CareerBank from a plain dict.

    The single validation path: load_bank feeds it yaml-derived dicts, the
    bank_provider feeds it the parsed `career-bank` json resource.
    """
    if not isinstance(data, dict):
        raise CareerBankError("career bank data must be a mapping")
    profile = data.get("profile")
    if not isinstance(profile, dict):
        raise CareerBankError("profile: must be a mapping")
    if not profile.get("name"):
        raise CareerBankError("profile: missing required field 'name'")
    if not profile.get("email"):
        raise CareerBankError("profile: missing required field 'email'")

    skills = data.get("skills") or []
    if not isinstance(skills, list):
        raise CareerBankError("skills: must be a list")

    raw_experiences = data.get("experiences") or []
    if not isinstance(raw_experiences, list):
        raise CareerBankError("experiences: must be a list")

    experiences: list = []
    facts: dict = {}
    fact_ids: set = set()
    for i, doc in enumerate(raw_experiences):
        if not isinstance(doc, dict):
            raise CareerBankError(f"experiences[{i}]: must be a mapping")
        where = f"experiences[{i}] ({doc.get('company') or 'unknown company'})"
        company = doc.get("company")
        title = doc.get("title")
        start = doc.get("start")
        end = doc.get("end")
        if not company:
            raise CareerBankError(f"{where}: missing required field 'company'")
        if not title:
            raise CareerBankError(f"{where}: missing required field 'title'")
        raw_facts = doc.get("facts") or []
        if not isinstance(raw_facts, list):
            raise CareerBankError(f"{where}: field 'facts' must be a list")
        parsed_facts = []
        for raw in raw_facts:
            fact = _parse_fact(raw, where, company, title, start, end, fact_ids)
            fact_ids.add(fact["id"])
            facts[fact["id"]] = fact
            parsed_facts.append(fact)
        experiences.append({**doc, "facts": parsed_facts})

    return CareerBank(profile=profile, skills=skills, experiences=experiences,
                      facts=facts, fact_ids=fact_ids)


def load_bank(path: str) -> CareerBank:
    root = Path(path)
    if not root.is_dir():
        raise CareerBankError(f"career bank directory not found: {path}")

    profile_path = root / "profile.yaml"
    if not profile_path.exists():
        raise CareerBankError(f"profile.yaml: missing required file in {path}")
    profile = _load_yaml(profile_path)

    skills_path = root / "skills.yaml"
    skills: list = []
    if skills_path.exists():
        skills_doc = _load_yaml(skills_path)
        skills = skills_doc.get("skills") or []
        if not isinstance(skills, list):
            raise CareerBankError("skills.yaml: field 'skills' must be a list")

    exp_dir = root / "experience"
    experiences: list = []
    if exp_dir.is_dir():
        for exp_file in sorted(exp_dir.glob("*.yaml")):
            experiences.append(_load_yaml(exp_file))

    return from_dict({"profile": profile, "skills": skills, "experiences": experiences})

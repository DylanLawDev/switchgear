import pytest
import json

from switchgear.career.bank import CareerBankError, from_dict, load_bank


def test_repo_career_dir_is_intentionally_empty():
    # spec §3.6: no preloaded example career data ships in the repo. The
    # (optional) local-YAML fallback still works — see the other tests in
    # this file — but career/ itself must not contain a seedable profile.
    with pytest.raises(CareerBankError):
        load_bank("career")


def test_missing_dir_raises():
    with pytest.raises(CareerBankError):
        load_bank("does-not-exist-career-dir")


def test_missing_profile_name_raises(tmp_path):
    (tmp_path / "profile.yaml").write_text("email: a@b.com\n")
    (tmp_path / "skills.yaml").write_text("skills: []\n")
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "company: Corp\ntitle: Eng\nfacts:\n"
        "  - id: a-fact\n    text: did a thing\n    skills: [python]\n"
    )
    with pytest.raises(CareerBankError) as exc:
        load_bank(str(tmp_path))
    assert "profile" in str(exc.value)
    assert "name" in str(exc.value)


def test_missing_profile_email_raises(tmp_path):
    (tmp_path / "profile.yaml").write_text("name: Someone\n")
    (tmp_path / "skills.yaml").write_text("skills: []\n")
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "company: Corp\ntitle: Eng\nfacts:\n"
        "  - id: a-fact\n    text: did a thing\n    skills: [python]\n"
    )
    with pytest.raises(CareerBankError) as exc:
        load_bank(str(tmp_path))
    assert "profile" in str(exc.value)
    assert "email" in str(exc.value)


def _write_valid_profile(tmp_path):
    (tmp_path / "profile.yaml").write_text("name: Someone\nemail: a@b.com\n")
    (tmp_path / "skills.yaml").write_text("skills: []\n")


def test_duplicate_fact_ids_across_files_raise(tmp_path):
    _write_valid_profile(tmp_path)
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp-a.yaml").write_text(
        "company: A Corp\ntitle: Eng\nfacts:\n"
        "  - id: dup-fact\n    text: did a thing\n    skills: [python]\n"
    )
    (exp_dir / "corp-b.yaml").write_text(
        "company: B Corp\ntitle: Eng\nfacts:\n"
        "  - id: dup-fact\n    text: did another thing\n    skills: [python]\n"
    )
    with pytest.raises(CareerBankError) as exc:
        load_bank(str(tmp_path))
    assert "dup-fact" in str(exc.value)


def test_bad_fact_id_pattern_raises(tmp_path):
    _write_valid_profile(tmp_path)
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "company: Corp\ntitle: Eng\nfacts:\n"
        "  - id: Bad_ID!\n    text: did a thing\n    skills: [python]\n"
    )
    with pytest.raises(CareerBankError) as exc:
        load_bank(str(tmp_path))
    assert "Bad_ID!" in str(exc.value) or "corp.yaml" in str(exc.value)


def test_fact_missing_text_raises(tmp_path):
    _write_valid_profile(tmp_path)
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "company: Corp\ntitle: Eng\nfacts:\n"
        "  - id: a-fact\n    text: \"\"\n    skills: [python]\n"
    )
    with pytest.raises(CareerBankError) as exc:
        load_bank(str(tmp_path))
    assert "text" in str(exc.value)


def test_experience_missing_company_raises(tmp_path):
    _write_valid_profile(tmp_path)
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "title: Eng\nfacts:\n"
        "  - id: a-fact\n    text: did a thing\n    skills: [python]\n"
    )
    with pytest.raises(CareerBankError) as exc:
        load_bank(str(tmp_path))
    assert "company" in str(exc.value)


def test_experience_missing_title_raises(tmp_path):
    _write_valid_profile(tmp_path)
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "company: Corp\nfacts:\n"
        "  - id: a-fact\n    text: did a thing\n    skills: [python]\n"
    )
    with pytest.raises(CareerBankError) as exc:
        load_bank(str(tmp_path))
    assert "title" in str(exc.value)


def test_skills_must_be_lowercase_strings(tmp_path):
    _write_valid_profile(tmp_path)
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "company: Corp\ntitle: Eng\nfacts:\n"
        "  - id: a-fact\n    text: did a thing\n    skills: [Python]\n"
    )
    with pytest.raises(CareerBankError) as exc:
        load_bank(str(tmp_path))
    assert "skills" in str(exc.value)


def test_facts_map_carries_company_and_title_context(tmp_path):
    _write_valid_profile(tmp_path)
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "company: Acme\ntitle: Staff Eng\nstart: 2021-01\nend: 2023-06\nfacts:\n"
        "  - id: a-fact\n    text: did a thing\n    skills: [python]\n"
        '    metric: "10%"\n'
    )
    bank = load_bank(str(tmp_path))
    fact = bank.facts["a-fact"]
    assert fact["company"] == "Acme"
    assert fact["title"] == "Staff Eng"
    assert fact["text"] == "did a thing"
    assert fact["metric"] == "10%"
    assert fact["skills"] == ["python"]
    assert fact["start"] == "2021-01"
    assert fact["end"] == "2023-06"


def test_facts_map_canonicalizes_full_iso_dates_to_strings(tmp_path):
    # yaml resolves `2022-01-15` to datetime.date; facts must carry the
    # canonical string form so the seeded json resource round-trips exactly
    _write_valid_profile(tmp_path)
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "company: Acme\ntitle: Staff Eng\nstart: 2022-01-15\nend: 2023-06-30\nfacts:\n"
        "  - id: a-fact\n    text: did a thing\n    skills: [python]\n"
    )
    bank = load_bank(str(tmp_path))
    fact = bank.facts["a-fact"]
    assert fact["start"] == "2022-01-15"
    assert fact["end"] == "2023-06-30"


def test_facts_map_start_and_end_default_to_none_when_absent(tmp_path):
    _write_valid_profile(tmp_path)
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "company: Acme\ntitle: Staff Eng\nfacts:\n"
        "  - id: a-fact\n    text: did a thing\n    skills: [python]\n"
    )
    bank = load_bank(str(tmp_path))
    fact = bank.facts["a-fact"]
    assert fact["start"] is None
    assert fact["end"] is None


def test_summary_text_is_deterministic_and_compact(tmp_path):
    _write_valid_profile(tmp_path)
    (tmp_path / "profile.yaml").write_text(
        "name: Someone\nemail: a@b.com\nheadline: Engineer\nsummary: A concise summary.\n"
    )
    (tmp_path / "skills.yaml").write_text(
        "skills:\n  - {name: Python, years: 5}\n  - {name: FastAPI, years: 3}\n"
    )
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "company: Acme\ntitle: Staff Eng\nfacts:\n"
        "  - id: a-fact\n    text: did a thing\n    skills: [python]\n"
    )
    bank = load_bank(str(tmp_path))
    text1 = bank.summary_text()
    text2 = bank.summary_text()
    assert text1 == text2
    assert "Someone" in text1
    assert "Engineer" in text1
    assert "A concise summary." in text1
    assert "Python (5y)" in text1
    assert "FastAPI (3y)" in text1
    assert "Acme — Staff Eng: did a thing" in text1


# ---------- from_dict (shared validation path with load_bank) ----------


def _valid_dict():
    return {
        "profile": {"name": "Someone", "email": "a@b.com"},
        "skills": [{"name": "Python", "years": 5}],
        "experiences": [{
            "company": "Acme", "title": "Staff Eng", "start": "2021-01", "end": None,
            "facts": [{"id": "a-fact", "text": "did a thing", "skills": ["python"],
                       "metric": "10%"}],
        }],
    }


def test_from_dict_valid_builds_full_bank():
    bank = from_dict(_valid_dict())
    assert bank.profile["name"] == "Someone"
    assert bank.skills == [{"name": "Python", "years": 5}]
    assert bank.fact_ids == {"a-fact"}
    fact = bank.facts["a-fact"]
    assert fact["company"] == "Acme"
    assert fact["title"] == "Staff Eng"
    assert fact["start"] == "2021-01"
    assert fact["metric"] == "10%"
    assert bank.experiences[0]["facts"] == [fact]


def test_from_dict_rejects_non_mapping():
    with pytest.raises(CareerBankError):
        from_dict(["not", "a", "mapping"])


def test_from_dict_rejects_missing_profile():
    data = _valid_dict()
    data["profile"] = None
    with pytest.raises(CareerBankError, match="profile"):
        from_dict(data)


def test_from_dict_rejects_profile_without_name():
    data = _valid_dict()
    del data["profile"]["name"]
    with pytest.raises(CareerBankError, match="name"):
        from_dict(data)


def test_from_dict_rejects_profile_without_email():
    data = _valid_dict()
    del data["profile"]["email"]
    with pytest.raises(CareerBankError, match="email"):
        from_dict(data)


def test_from_dict_rejects_non_list_skills():
    data = _valid_dict()
    data["skills"] = {"name": "Python"}
    with pytest.raises(CareerBankError, match="skills"):
        from_dict(data)


def test_from_dict_rejects_non_list_experiences():
    data = _valid_dict()
    data["experiences"] = "Acme"
    with pytest.raises(CareerBankError, match="experiences"):
        from_dict(data)


def test_from_dict_rejects_experience_missing_company():
    data = _valid_dict()
    del data["experiences"][0]["company"]
    with pytest.raises(CareerBankError, match="company"):
        from_dict(data)


def test_from_dict_rejects_experience_missing_title():
    data = _valid_dict()
    del data["experiences"][0]["title"]
    with pytest.raises(CareerBankError, match="title"):
        from_dict(data)


def test_from_dict_rejects_duplicate_fact_ids():
    data = _valid_dict()
    data["experiences"].append({
        "company": "B Corp", "title": "Eng",
        "facts": [{"id": "a-fact", "text": "again", "skills": []}]})
    with pytest.raises(CareerBankError, match="a-fact"):
        from_dict(data)


def test_from_dict_rejects_bad_fact_id():
    data = _valid_dict()
    data["experiences"][0]["facts"][0]["id"] = "Bad_ID!"
    with pytest.raises(CareerBankError, match="id"):
        from_dict(data)


def test_from_dict_rejects_fact_missing_text():
    data = _valid_dict()
    data["experiences"][0]["facts"][0]["text"] = ""
    with pytest.raises(CareerBankError, match="text"):
        from_dict(data)


def test_from_dict_rejects_uppercase_fact_skills():
    data = _valid_dict()
    data["experiences"][0]["facts"][0]["skills"] = ["Python"]
    with pytest.raises(CareerBankError, match="skills"):
        from_dict(data)


def test_load_bank_equals_from_dict_of_its_serialization(tmp_path):
    _write_valid_profile(tmp_path)
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "corp.yaml").write_text(
        "company: Acme\ntitle: Staff Eng\nstart: 2021-01\nend: 2023-06\nfacts:\n"
        "  - id: a-fact\n    text: did a thing\n    skills: [python]\n"
    )
    bank = load_bank(str(tmp_path))
    data = {"profile": bank.profile, "skills": bank.skills,
            "experiences": bank.experiences}
    rebuilt = from_dict(json.loads(json.dumps(data, default=str)))
    assert rebuilt.profile == bank.profile
    assert rebuilt.fact_ids == bank.fact_ids
    assert rebuilt.facts.keys() == bank.facts.keys()

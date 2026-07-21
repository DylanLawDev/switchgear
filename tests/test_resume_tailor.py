import json

import pytest

from switchgear.gateway import Completion
from switchgear.career.bank import load_bank
from switchgear.jobs.model import make_job
from switchgear.resume.tailor import (
    TailorError,
    build_tailor_messages,
    parse_selection,
    tailor_selection,
    validate_selection,
)


class FakeCompleteGateway:
    def __init__(self, completions):
        self._completions = list(completions)
        self.calls: list[dict] = []

    async def complete(self, tier, messages, tools=None):
        self.calls.append({"tier": tier, "messages": list(messages)})
        return self._completions.pop(0)


def _bank(tmp_path):
    (tmp_path / "profile.yaml").write_text(
        "name: Alex Example\nemail: owner@example.com\nheadline: Software engineer\n"
        "summary: Builds reliable backend systems.\n"
    )
    (tmp_path / "skills.yaml").write_text(
        "skills:\n  - {name: Python, years: 5}\n  - {name: FastAPI, years: 3}\n"
    )
    exp_dir = tmp_path / "experience"
    exp_dir.mkdir()
    (exp_dir / "acme.yaml").write_text(
        "company: Acme Corp\ntitle: Senior Engineer\nstart: 2022-01\nend: present\n"
        "facts:\n"
        "  - id: cut-latency\n"
        '    text: "Cut checkout p99 latency 40% by rewriting the cart service"\n'
        "    skills: [python, performance]\n"
        '    metric: "40% p99 reduction"\n'
        "  - id: led-migration\n"
        '    text: "Led migration to a new billing platform"\n'
        "    skills: [python]\n"
    )
    return load_bank(str(tmp_path))


def _job(**kwargs):
    defaults = dict(
        url="https://boards.greenhouse.io/acme/jobs/1",
        title="Backend Engineer",
        company="Globex",
        description="We need a backend engineer with Python experience.",
        source="greenhouse",
    )
    defaults.update(kwargs)
    return make_job(**defaults)


def _selection(bullets):
    return {
        "summary": "A concise summary.",
        "sections": [
            {
                "heading": "Experience",
                "entries": [
                    {
                        "company": "Acme Corp",
                        "title": "Senior Engineer",
                        "dates": "2022-01 - present",
                        "bullets": bullets,
                    }
                ],
            }
        ],
    }


# ---------- build_tailor_messages ----------


def test_messages_include_fact_ids_and_contract_wording(tmp_path):
    bank = _bank(tmp_path)
    messages = build_tailor_messages(_job(), bank)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    full_text = messages[0]["content"] + messages[1]["content"]
    assert "cut-latency" in full_text
    assert "led-migration" in full_text
    assert "fact_id" in full_text
    assert "never invent" in messages[0]["content"].lower()
    assert "We need a backend engineer" in messages[1]["content"]


def test_messages_truncate_job_description_to_6000_chars(tmp_path):
    bank = _bank(tmp_path)
    job = _job(description="B" * 7000)
    messages = build_tailor_messages(job, bank)
    user_content = messages[1]["content"]
    assert "B" * 6000 in user_content
    assert "B" * 6001 not in user_content


# ---------- parse_selection ----------


def test_parse_selection_plain_json():
    content = json.dumps({"summary": "s", "sections": []})
    assert parse_selection(content) == {"summary": "s", "sections": []}


def test_parse_selection_fenced_json():
    body = json.dumps({"summary": "s", "sections": []})
    content = f"```json\n{body}\n```"
    assert parse_selection(content) == {"summary": "s", "sections": []}


def test_parse_selection_plain_fence_without_json_tag():
    body = json.dumps({"summary": "s", "sections": []})
    content = f"```\n{body}\n```"
    assert parse_selection(content) == {"summary": "s", "sections": []}


def test_parse_selection_non_json_raises():
    with pytest.raises(TailorError):
        parse_selection("not json at all")


def test_parse_selection_missing_summary_raises():
    with pytest.raises(TailorError):
        parse_selection(json.dumps({"sections": []}))


def test_parse_selection_missing_sections_raises():
    with pytest.raises(TailorError):
        parse_selection(json.dumps({"summary": "s"}))


def test_parse_selection_summary_not_str_raises():
    with pytest.raises(TailorError):
        parse_selection(json.dumps({"summary": 5, "sections": []}))


def test_parse_selection_sections_not_list_raises():
    with pytest.raises(TailorError):
        parse_selection(json.dumps({"summary": "s", "sections": {}}))


def test_parse_selection_section_not_dict_raises():
    content = json.dumps({"summary": "s", "sections": ["Experience"]})
    with pytest.raises(TailorError) as exc:
        parse_selection(content)
    assert "section" in str(exc.value)


def test_parse_selection_entries_not_list_raises():
    content = json.dumps(
        {"summary": "s", "sections": [{"heading": "Experience", "entries": "oops"}]}
    )
    with pytest.raises(TailorError) as exc:
        parse_selection(content)
    assert "entries" in str(exc.value)


def test_parse_selection_entry_not_dict_raises():
    content = json.dumps(
        {"summary": "s", "sections": [{"heading": "Experience", "entries": ["oops"]}]}
    )
    with pytest.raises(TailorError) as exc:
        parse_selection(content)
    assert "entry" in str(exc.value)


def test_parse_selection_bullets_not_list_raises():
    content = json.dumps(
        {
            "summary": "s",
            "sections": [
                {"heading": "Experience", "entries": [{"bullets": {"fact_id": "x"}}]}
            ],
        }
    )
    with pytest.raises(TailorError) as exc:
        parse_selection(content)
    assert "bullets" in str(exc.value)


def test_parse_selection_bullets_string_raises():
    content = json.dumps(
        {
            "summary": "s",
            "sections": [
                {"heading": "Experience", "entries": [{"bullets": "not-a-list"}]}
            ],
        }
    )
    with pytest.raises(TailorError) as exc:
        parse_selection(content)
    assert "bullets" in str(exc.value)


def test_parse_selection_bullet_not_dict_raises():
    content = json.dumps(
        {
            "summary": "s",
            "sections": [
                {"heading": "Experience", "entries": [{"bullets": ["not-a-dict"]}]}
            ],
        }
    )
    with pytest.raises(TailorError) as exc:
        parse_selection(content)
    assert "bullet" in str(exc.value)


def test_parse_selection_entries_absent_defaults_to_empty():
    content = json.dumps({"summary": "s", "sections": [{"heading": "Skills"}]})
    result = parse_selection(content)
    assert result["sections"] == [{"heading": "Skills"}]


def test_parse_selection_bullets_absent_defaults_to_empty():
    content = json.dumps(
        {"summary": "s", "sections": [{"heading": "Skills", "entries": [{}]}]}
    )
    result = parse_selection(content)
    assert result["sections"][0]["entries"] == [{}]


# ---------- validate_selection ----------


def test_validate_selection_normalizes_verbatim_null_bullet(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([{"fact_id": "cut-latency", "text": None}])
    result = validate_selection(selection, bank)
    bullet = result["sections"][0]["entries"][0]["bullets"][0]
    assert bullet == {
        "fact_id": "cut-latency",
        "text": None,
        "source_text": bank.facts["cut-latency"]["text"],
        "rephrased": False,
    }


def test_validate_selection_normalizes_verbatim_equal_bullet(tmp_path):
    bank = _bank(tmp_path)
    source = bank.facts["cut-latency"]["text"]
    selection = _selection([{"fact_id": "cut-latency", "text": source}])
    result = validate_selection(selection, bank)
    bullet = result["sections"][0]["entries"][0]["bullets"][0]
    assert bullet["rephrased"] is False
    assert bullet["text"] == source
    assert bullet["source_text"] == source


def test_validate_selection_whitespace_only_difference_is_not_rephrased(tmp_path):
    bank = _bank(tmp_path)
    source = bank.facts["cut-latency"]["text"]
    spaced = "   ".join(source.split())
    selection = _selection([{"fact_id": "cut-latency", "text": spaced}])
    result = validate_selection(selection, bank)
    bullet = result["sections"][0]["entries"][0]["bullets"][0]
    assert bullet["rephrased"] is False


def test_validate_selection_rephrased_bullet(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection(
        [{"fact_id": "cut-latency", "text": "Reduced p99 checkout latency by 40%"}]
    )
    result = validate_selection(selection, bank)
    bullet = result["sections"][0]["entries"][0]["bullets"][0]
    assert bullet["rephrased"] is True
    assert bullet["source_text"] == bank.facts["cut-latency"]["text"]


def test_validate_selection_unknown_fact_id_raises_naming_it(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([{"fact_id": "made-up-fact", "text": None}])
    with pytest.raises(TailorError) as exc:
        validate_selection(selection, bank)
    assert "made-up-fact" in str(exc.value)


def test_validate_selection_missing_fact_id_key_raises(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([{"text": "no fact id here"}])
    with pytest.raises(TailorError):
        validate_selection(selection, bank)


def test_validate_selection_collects_all_bad_ids_before_raising(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection(
        [
            {"fact_id": "bad-one", "text": None},
            {"fact_id": "bad-two", "text": None},
        ]
    )
    with pytest.raises(TailorError) as exc:
        validate_selection(selection, bank)
    assert "bad-one" in str(exc.value)
    assert "bad-two" in str(exc.value)


def test_validate_selection_non_string_text_raises(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([{"fact_id": "cut-latency", "text": 42}])
    with pytest.raises(TailorError) as exc:
        validate_selection(selection, bank)
    assert "cut-latency" in str(exc.value)


def test_validate_selection_list_text_raises(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([{"fact_id": "cut-latency", "text": ["not", "a", "string"]}])
    with pytest.raises(TailorError) as exc:
        validate_selection(selection, bank)
    assert "cut-latency" in str(exc.value)


def test_validate_selection_normalizes_across_all_sections(tmp_path):
    bank = _bank(tmp_path)
    selection = {
        "summary": "S",
        "sections": [
            {
                "heading": "Experience",
                "entries": [
                    {
                        "company": "Acme Corp",
                        "title": "Senior Engineer",
                        "dates": "2022 - present",
                        "bullets": [{"fact_id": "cut-latency", "text": None}],
                    }
                ],
            },
            {
                "heading": "Skills",
                "entries": [{"bullets": [{"fact_id": "led-migration", "text": None}]}],
            },
        ],
    }
    result = validate_selection(selection, bank)
    exp_bullet = result["sections"][0]["entries"][0]["bullets"][0]
    skill_bullet = result["sections"][1]["entries"][0]["bullets"][0]
    assert exp_bullet["source_text"] == bank.facts["cut-latency"]["text"]
    assert skill_bullet["source_text"] == bank.facts["led-migration"]["text"]


# ---------- validate_selection: header grounding ----------


def test_validate_selection_invented_company_raises(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([{"fact_id": "cut-latency", "text": None}])
    selection["sections"][0]["entries"][0]["company"] = "Made Up Corp"
    with pytest.raises(TailorError) as exc:
        validate_selection(selection, bank)
    assert "Made Up Corp" in str(exc.value)


def test_validate_selection_invented_title_raises(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([{"fact_id": "cut-latency", "text": None}])
    selection["sections"][0]["entries"][0]["title"] = "Chief Wizard"
    with pytest.raises(TailorError) as exc:
        validate_selection(selection, bank)
    assert "Chief Wizard" in str(exc.value)


def test_validate_selection_matching_header_overwrites_dates_ignoring_llm_value(tmp_path):
    bank = _bank(tmp_path)
    selection = _selection([{"fact_id": "cut-latency", "text": None}])
    entry = selection["sections"][0]["entries"][0]
    entry["dates"] = "made up dates the LLM invented"
    result = validate_selection(selection, bank)
    result_entry = result["sections"][0]["entries"][0]
    assert result_entry["company"] == "Acme Corp"
    assert result_entry["title"] == "Senior Engineer"
    assert result_entry["dates"] == "2022-01 – present"


def test_validate_selection_header_entry_missing_start_or_end_has_no_dates(tmp_path):
    bank = _bank(tmp_path)
    # led-migration also belongs to acme (start=2022-01, end=present), so overwrite
    # exercises the derived-dates branch; simulate missing bank dates directly.
    bank.facts["cut-latency"]["start"] = None
    selection = _selection([{"fact_id": "cut-latency", "text": None}])
    result = validate_selection(selection, bank)
    result_entry = result["sections"][0]["entries"][0]
    assert result_entry["dates"] is None


def test_validate_selection_facts_spanning_two_experiences_raises(tmp_path):
    bank = _bank(tmp_path)
    (tmp_path / "experience" / "globex.yaml").write_text(
        "company: Globex\ntitle: Staff Engineer\nstart: 2019-01\nend: 2021-12\n"
        "facts:\n"
        "  - id: shipped-thing\n"
        '    text: "Shipped a thing at Globex"\n'
        "    skills: [python]\n"
    )
    bank = load_bank(str(tmp_path))
    selection = _selection(
        [
            {"fact_id": "cut-latency", "text": None},
            {"fact_id": "shipped-thing", "text": None},
        ]
    )
    with pytest.raises(TailorError) as exc:
        validate_selection(selection, bank)
    assert "multiple experiences" in str(exc.value)


def test_validate_selection_skills_entry_without_header_strips_llm_dates(tmp_path):
    bank = _bank(tmp_path)
    selection = {
        "summary": "S",
        "sections": [
            {
                "heading": "Skills",
                "entries": [
                    {
                        "dates": "not grounded",
                        "bullets": [{"fact_id": "led-migration", "text": None}],
                    }
                ],
            }
        ],
    }
    result = validate_selection(selection, bank)
    entry = result["sections"][0]["entries"][0]
    assert entry["dates"] is None
    assert "company" not in entry
    assert "title" not in entry


# ---------- tailor_selection ----------


async def test_tailor_selection_happy_path_uses_writing_tier(tmp_path):
    bank = _bank(tmp_path)
    content = json.dumps(
        {
            "summary": "A concise, grounded summary.",
            "sections": [
                {
                    "heading": "Experience",
                    "entries": [
                        {
                            "company": "Acme Corp",
                            "title": "Senior Engineer",
                            "dates": "2022 - present",
                            "bullets": [
                                {"fact_id": "cut-latency", "text": None},
                                {
                                    "fact_id": "led-migration",
                                    "text": "Led billing platform migration",
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    )
    gateway = FakeCompleteGateway([Completion(message={"content": content}, usage=42)])

    result = await tailor_selection(gateway, _job(), bank)

    assert gateway.calls[0]["tier"] == "writing"
    bullets = result["sections"][0]["entries"][0]["bullets"]
    assert bullets[0]["rephrased"] is False
    assert bullets[0]["source_text"] == bank.facts["cut-latency"]["text"]
    assert bullets[1]["rephrased"] is True
    assert bullets[1]["source_text"] == bank.facts["led-migration"]["text"]


async def test_tailor_selection_fenced_json(tmp_path):
    bank = _bank(tmp_path)
    body = json.dumps(
        {
            "summary": "S",
            "sections": [
                {
                    "heading": "Experience",
                    "entries": [
                        {
                            "company": "Acme Corp",
                            "title": "Senior Engineer",
                            "dates": "2022 - present",
                            "bullets": [{"fact_id": "cut-latency", "text": None}],
                        }
                    ],
                }
            ],
        }
    )
    content = f"```json\n{body}\n```"
    gateway = FakeCompleteGateway([Completion(message={"content": content}, usage=1)])

    result = await tailor_selection(gateway, _job(), bank)

    assert result["sections"][0]["entries"][0]["bullets"][0]["fact_id"] == "cut-latency"


async def test_tailor_selection_invented_fact_id_raises(tmp_path):
    bank = _bank(tmp_path)
    content = json.dumps(
        {
            "summary": "S",
            "sections": [
                {
                    "heading": "Experience",
                    "entries": [
                        {
                            "company": "Acme Corp",
                            "title": "Senior Engineer",
                            "dates": "2022 - present",
                            "bullets": [{"fact_id": "invented-fact", "text": None}],
                        }
                    ],
                }
            ],
        }
    )
    gateway = FakeCompleteGateway([Completion(message={"content": content}, usage=1)])

    with pytest.raises(TailorError) as exc:
        await tailor_selection(gateway, _job(), bank)
    assert "invented-fact" in str(exc.value)


async def test_tailor_selection_missing_fact_id_key_raises(tmp_path):
    bank = _bank(tmp_path)
    content = json.dumps(
        {
            "summary": "S",
            "sections": [
                {
                    "heading": "Experience",
                    "entries": [
                        {
                            "company": "Acme Corp",
                            "title": "Senior Engineer",
                            "dates": "2022 - present",
                            "bullets": [{"text": "no id"}],
                        }
                    ],
                }
            ],
        }
    )
    gateway = FakeCompleteGateway([Completion(message={"content": content}, usage=1)])

    with pytest.raises(TailorError):
        await tailor_selection(gateway, _job(), bank)


async def test_tailor_selection_non_json_raises(tmp_path):
    bank = _bank(tmp_path)
    gateway = FakeCompleteGateway([Completion(message={"content": "not json"}, usage=1)])

    with pytest.raises(TailorError):
        await tailor_selection(gateway, _job(), bank)

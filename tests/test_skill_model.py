import pytest

from switchgear.skills.model import SkillParseError, parse_skill, render_skill

GOOD = """---
name: daily-brief
description: Email me a daily brief
tools: [http_fetch, send_email]
schedule: "0 13 * * *"
---
1. Fetch the news.
2. Email the owner a summary.
"""


def test_parse_roundtrip():
    doc = parse_skill(GOOD)
    assert doc["name"] == "daily-brief"
    assert doc["description"] == "Email me a daily brief"
    assert doc["tools"] == ["http_fetch", "send_email"]
    assert doc["schedule"] == "0 13 * * *"
    assert doc["body"].startswith("1. Fetch")
    assert parse_skill(render_skill(doc)) == doc


def test_schedule_optional():
    text = GOOD.replace('schedule: "0 13 * * *"\n', "")
    doc = parse_skill(text)
    assert doc["schedule"] is None
    assert "schedule" not in render_skill(doc)


def test_tools_default_empty():
    text = GOOD.replace("tools: [http_fetch, send_email]\n", "")
    assert parse_skill(text)["tools"] == []


@pytest.mark.parametrize("mutation", [
    lambda t: t.replace("---\n", "", 1),                             # no frontmatter
    lambda t: t.replace("name: daily-brief\n", ""),                  # missing name
    lambda t: t.replace("description: Email me a daily brief\n", ""),  # missing description
    lambda t: t.replace("daily-brief", "Bad Name!"),                # invalid name
    lambda t: t.replace("[http_fetch, send_email]", "http_fetch"),  # tools not a list
])
def test_parse_errors(mutation):
    with pytest.raises(SkillParseError):
        parse_skill(mutation(GOOD))

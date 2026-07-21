import pytest

from switchgear.workflows.model import WorkflowParseError, parse_duration, parse_workflow

GENS = {"tailor-resume"}
EXECS = {"submit-application"}

VALID = """---
schema_version: 1
name: job-hunt
description: Find, score, and apply to jobs
items:
  label: job
  label_plural: jobs
  collection: jobs
  title_field: title
  expected_update_period: 2d
  fields:
    title: {type: text}
    score: {type: score, max: 100}
    url: {type: url}
    first_seen: {type: timestamp}
  list_fields: [title, score]
  sort: [-score, -first_seen]
artifacts:
  label: resume
  label_plural: resumes
  collection: resumes
  title_field: job_title
  key_field: rid
  item_ref_field: job_key
  fields:
    job_title: {type: text}
    html_file: {type: artifact}
actions:
  label: application
  label_plural: applications
  collection: applications
  key_field: app_id
  item_ref_field: job_key
  executor: submit-application
intake:
  skills: [job-search]
generate:
  plugin: tailor-resume
  label: Tailor resume
---
Owner-facing description body.
"""


def parse(text=VALID, **kw):
    kw.setdefault("generators", GENS)
    kw.setdefault("executors", EXECS)
    return parse_workflow(text, **kw)


def test_parse_duration():
    assert parse_duration("2d") == 2 * 86400
    assert parse_duration("7d") == 7 * 86400
    assert parse_duration("90m") == 90 * 60
    assert parse_duration("6h") == 6 * 3600
    with pytest.raises(WorkflowParseError):
        parse_duration("soon")


def test_valid_definition_parses_with_defaults():
    wf = parse()
    assert wf["schema_version"] == 1
    assert wf["name"] == "job-hunt"
    assert wf["items"]["collection"] == "jobs"
    assert wf["items"]["key_field"] == "key"          # default
    assert wf["items"]["expected_update_period"] == 2 * 86400
    assert wf["items"]["retention"] is None
    assert wf["items"]["detail_fields"] is None
    assert wf["items"]["sort"] == ["-score", "-first_seen"]
    assert wf["artifacts"]["key_field"] == "rid"
    assert wf["artifacts"]["item_ref_field"] == "job_key"
    assert wf["actions"]["executor"] == "submit-application"
    assert wf["actions"]["approval_ttl"] == 7 * 86400  # default
    assert wf["actions"]["draft_ttl"] == 30 * 86400    # default
    assert wf["intake"]["skills"] == ["job-search"]
    assert wf["generate"] == {"plugin": "tailor-resume", "label": "Tailor resume"}
    assert wf["body"].startswith("Owner-facing")


def test_default_collections_derive_from_name():
    text = VALID.replace("  collection: jobs\n", "").replace(
        "  collection: resumes\n", "").replace("  collection: applications\n", "")
    wf = parse(text)
    assert wf["items"]["collection"] == "wf-job-hunt-items"
    assert wf["artifacts"]["collection"] == "wf-job-hunt-artifacts"
    assert wf["actions"]["collection"] == "wf-job-hunt-actions"


def test_default_sort_is_created_at_desc():
    text = VALID.replace("  sort: [-score, -first_seen]\n", "")
    assert parse(text)["items"]["sort"] == ["-created_at"]


def test_rejects_unknown_schema_version():
    with pytest.raises(WorkflowParseError, match="schema_version"):
        parse(VALID.replace("schema_version: 1", "schema_version: 99"))


def test_rejects_bad_name():
    with pytest.raises(WorkflowParseError, match="name"):
        parse(VALID.replace("name: job-hunt", "name: Job Hunt!"))


def test_rejects_unknown_field_type():
    with pytest.raises(WorkflowParseError, match="type"):
        parse(VALID.replace("{type: url}", "{type: hyperlink}"))


def test_rejects_list_fields_not_declared():
    with pytest.raises(WorkflowParseError, match="list_fields"):
        parse(VALID.replace("list_fields: [title, score]", "list_fields: [title, nope]"))


def test_rejects_sort_field_not_declared():
    with pytest.raises(WorkflowParseError, match="sort"):
        parse(VALID.replace("sort: [-score, -first_seen]", "sort: [-bogus]"))


def test_rejects_unknown_executor():
    with pytest.raises(WorkflowParseError, match="executor"):
        parse(executors=set())


def test_rejects_unknown_generator():
    with pytest.raises(WorkflowParseError, match="plugin"):
        parse(generators=set())


def test_actions_and_artifacts_and_generate_are_optional():
    text = """---
schema_version: 1
name: intake-only
description: just items
items:
  label: thing
  label_plural: things
  title_field: title
  fields:
    title: {type: text}
intake:
  skills: []
---
Body.
"""
    wf = parse(text)
    assert wf["artifacts"] is None
    assert wf["actions"] is None
    assert wf["generate"] is None


def test_missing_frontmatter_rejected():
    with pytest.raises(WorkflowParseError, match="frontmatter"):
        parse("no frontmatter here")


def test_items_required():
    text = VALID.replace("items:", "items_gone:")
    with pytest.raises(WorkflowParseError, match="items"):
        parse(text)


def test_rejects_sort_on_non_numeric_field():
    with pytest.raises(WorkflowParseError, match="sort"):
        parse(VALID.replace("sort: [-score, -first_seen]", "sort: [-title]"))


def _with_ui_home(text: str, value: str) -> str:
    # insert after the description: line of a known-valid manifest
    return text.replace("description:", f"ui_home: {value}\ndescription:", 1)


def test_ui_home_defaults_to_workflows():
    assert parse()["ui_home"] == "workflows"


def test_ui_home_channels_accepted():
    assert parse(_with_ui_home(VALID, "channels"))["ui_home"] == "channels"


def test_ui_home_rejects_unknown_value():
    with pytest.raises(WorkflowParseError, match="ui_home"):
        parse(_with_ui_home(VALID, "sidebar"))

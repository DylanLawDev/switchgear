import asyncio

from switchgear.config import Settings
from switchgear.storage.memory import MemoryStorage
from switchgear.workflows.actions import (
    DraftResult,
    ExecutionAmbiguous,  # noqa: F401 -- forward-compat import check, used by Task 5/6
    ExecutionFailed,  # noqa: F401 -- forward-compat import check, used by Task 5/6
    GatedActionService,
    payload_hash,
    sanitize_field,
)
from switchgear.workflows.model import parse_workflow
from switchgear.workflows.registry import WorkflowPlugins

WF_TEXT = """---
schema_version: 1
name: test-flow
description: test workflow
items:
  label: thing
  label_plural: things
  title_field: title
  fields:
    title: {type: text}
actions:
  label: dispatch
  label_plural: dispatches
  executor: fake-exec
  approval_ttl: 7d
  draft_ttl: 30d
intake:
  skills: []
---
Body.
"""

FIELD = {"selector": "#a", "label": "A", "value": "x", "source": "profile",
         "needs_you": False, "kind": "text"}


class FakeExecutor:
    def __init__(self, draft_result=None, execute_result=None, execute_exc=None,
                 precondition_msg=None):
        self.draft_result = draft_result or DraftResult(fields=[dict(FIELD)])
        self.execute_result = execute_result or {}
        self.execute_exc = execute_exc
        self.precondition_msg = precondition_msg
        self.draft_calls, self.execute_calls = [], []

    async def draft(self, item):
        self.draft_calls.append(item)
        if isinstance(self.draft_result, Exception):
            raise self.draft_result
        return self.draft_result

    async def precondition(self, record):
        return self.precondition_msg

    async def execute(self, record):
        self.execute_calls.append(record)
        if self.execute_exc is not None:
            raise self.execute_exc
        return self.execute_result


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def make_service(executor=None, clock=None):
    storage = MemoryStorage()
    plugins = WorkflowPlugins()
    executor = executor or FakeExecutor()
    plugins.register_executor("fake-exec", executor)
    wf = parse_workflow(WF_TEXT, generators=set(), executors={"fake-exec"})
    svc = GatedActionService(storage, plugins, Settings(_env_file=None),
                             clock=clock or Clock())
    return svc, wf, storage, executor


async def seed_item(storage, wf, key="itm-1", title="Thing One"):
    await storage.put(wf["items"]["collection"], key, {"key": key, "title": title})


# ---------- hashing / sanitization ----------


def test_payload_hash_is_order_insensitive_within_field_dicts():
    a = [{"selector": "#a", "value": "1"}]
    b = [{"value": "1", "selector": "#a"}]
    assert payload_hash(a) == payload_hash(b)
    assert payload_hash(a) != payload_hash([{"selector": "#a", "value": "2"}])


def test_sanitize_field_keeps_known_keys_and_coerces():
    raw = {"selector": "#x", "label": 3, "value": None, "source": None,
           "needs_you": "yes", "kind": None, "hostile": "dropped"}
    out = sanitize_field(raw)
    assert out == {"selector": "#x", "label": "3", "value": "", "source": "agent",
                   "needs_you": True, "kind": "text"}
    assert sanitize_field({"no_selector": True}) is None
    assert sanitize_field("not a dict") is None


# ---------- start_draft ----------


async def test_start_draft_missing_item_errors():
    svc, wf, storage, _ = make_service()
    assert await svc.start_draft(wf, "nope") == {"error": "thing not found"}


async def test_start_draft_creates_sanitized_draft_with_lineage():
    executor = FakeExecutor(draft_result=DraftResult(
        fields=[{"selector": "#a", "label": "A", "value": "x", "hostile": 1}],
        notes="hello", extra={"job_title": "T", "status": "approved", "approval": {"x": 1}}))
    svc, wf, storage, _ = make_service(executor)
    await seed_item(storage, wf)
    rec = await svc.start_draft(wf, "itm-1")
    assert rec["status"] == "draft"                 # extra can never set status
    assert "approval" not in rec                    # ...nor approval
    assert rec["item_key"] == "itm-1"
    assert rec["job_title"] == "T"                  # benign extra merged
    assert rec["fields"][0]["selector"] == "#a"
    assert "hostile" not in rec["fields"][0]
    stored = await storage.get(wf["actions"]["collection"], rec["key"])
    assert stored["status"] == "draft"


async def test_start_draft_survives_executor_crash():
    executor = FakeExecutor(draft_result=RuntimeError("browser died"))
    svc, wf, storage, _ = make_service(executor)
    await seed_item(storage, wf)
    rec = await svc.start_draft(wf, "itm-1")
    assert rec["status"] == "draft"
    assert rec["fields"] == []
    assert "browser died" in rec["notes"]
    assert (await storage.get(wf["actions"]["collection"], rec["key"])) is not None


async def test_start_draft_audits():
    svc, wf, storage, _ = make_service()
    await seed_item(storage, wf)
    await svc.start_draft(wf, "itm-1")
    audit = await storage.query("audit")
    assert len(audit) == 1
    assert audit[0]["op"] == "draft" and audit[0]["workflow"] == "test-flow"


async def test_start_draft_reforces_system_timestamps():
    clock = Clock(now=1000.0)
    executor = FakeExecutor(draft_result=DraftResult(
        fields=[],
        extra={
            "created_at": 9e12,
            "updated_at": 9e12,
            "executed_at": 9e12,
        }))
    svc, wf, storage, _ = make_service(executor, clock)
    await seed_item(storage, wf)
    rec = await svc.start_draft(wf, "itm-1")
    # Service timestamps preserved, not overridden by executor
    assert rec["created_at"] == 1000.0
    assert rec["updated_at"] == 1000.0
    assert rec.get("executed_at") is None
    # Verify stored record matches
    stored = await storage.get(wf["actions"]["collection"], rec["key"])
    assert stored["created_at"] == 1000.0
    assert stored["updated_at"] == 1000.0
    assert stored.get("executed_at") is None


# ---------- update_fields / get / list ----------


async def test_update_fields_merges_and_stamps_updated_at():
    svc, wf, storage, _ = make_service(clock=(clock := Clock()))
    await seed_item(storage, wf)
    rec = await svc.start_draft(wf, "itm-1")
    clock.now = 2000.0
    out = await svc.update_fields(wf, rec["key"], [
        {"selector": "#a", "value": "new", "needs_you": True},
        {"selector": "#missing", "value": "ignored", "needs_you": False}])
    assert out["fields"][0]["value"] == "new"
    assert out["fields"][0]["needs_you"] is True
    assert out["updated_at"] == 2000.0


async def test_update_fields_blocked_outside_editable_statuses():
    svc, wf, storage, _ = make_service()
    await seed_item(storage, wf)
    rec = await svc.start_draft(wf, "itm-1")
    stored = await storage.get(wf["actions"]["collection"], rec["key"])
    stored["status"] = "rejected"
    await storage.put(wf["actions"]["collection"], rec["key"], stored)
    out = await svc.update_fields(wf, rec["key"], [])
    assert out == {"error": "dispatch is not editable"}


async def test_update_fields_missing_returns_none():
    svc, wf, storage, _ = make_service()
    assert await svc.update_fields(wf, "nope", []) is None


async def test_get_normalizes_legacy_submitted_to_executed():
    svc, wf, storage, _ = make_service()
    await storage.put(wf["actions"]["collection"], "act-legacy",
                      {"key": "act-legacy", "item_key": "itm-1",
                       "status": "submitted", "fields": [], "created_at": 999.0})
    rec = await svc.get(wf, "act-legacy")
    assert rec["status"] == "executed"
    # read-boundary only: the stored record is untouched
    assert (await storage.get(wf["actions"]["collection"], "act-legacy"))["status"] == "submitted"


async def test_list_normalized_and_newest_first():
    svc, wf, storage, _ = make_service()
    await seed_item(storage, wf)
    a = await svc.start_draft(wf, "itm-1")
    await storage.put(wf["actions"]["collection"], "act-old",
                      {"key": "act-old", "item_key": "itm-1", "status": "submitted",
                       "fields": [], "created_at": 1.0})
    rows = await svc.list(wf)
    assert [r["key"] for r in rows] == [a["key"], "act-old"]
    assert rows[1]["status"] == "executed"


# ---------- approve / reject ----------


async def draft_ready(svc, wf, storage):
    await seed_item(storage, wf)
    return await svc.start_draft(wf, "itm-1")


async def test_approve_blocks_while_needs_you_remains():
    executor = FakeExecutor(draft_result=DraftResult(
        fields=[{**FIELD, "needs_you": True}]))
    svc, wf, storage, _ = make_service(executor)
    rec = await draft_ready(svc, wf, storage)
    out = await svc.approve(wf, rec["key"], approved_by="me@example.com")
    assert out == {"error": "resolve NEEDS-YOU fields before approving"}


async def test_approve_pins_payload_hash_and_audits():
    svc, wf, storage, _ = make_service()
    rec = await draft_ready(svc, wf, storage)
    out = await svc.approve(wf, rec["key"], approved_by="me@example.com")
    assert out["status"] == "approved"
    assert out["approval"]["approved_by"] == "me@example.com"
    assert out["approval"]["payload_hash"] == payload_hash(out["fields"])
    ops = [a["op"] for a in await storage.query("audit")]
    assert "approve" in ops


async def test_approve_rejected_from_wrong_status():
    svc, wf, storage, _ = make_service()
    rec = await draft_ready(svc, wf, storage)
    await svc.approve(wf, rec["key"], approved_by="me")
    out = await svc.approve(wf, rec["key"], approved_by="me")
    assert out == {"error": "dispatch cannot be approved from its current status"}


async def test_approve_missing_returns_none():
    svc, wf, storage, _ = make_service()
    assert await svc.approve(wf, "nope", approved_by="me") is None


async def test_approval_expires_back_to_draft_lazily():
    clock = Clock()
    svc, wf, storage, _ = make_service(clock=clock)
    rec = await draft_ready(svc, wf, storage)
    await svc.approve(wf, rec["key"], approved_by="me")
    clock.now += 8 * 86400            # past the 7d approval_ttl
    # go through list(), which uses storage.query() -- that injects "_id"
    # into the record the TTL transition then persists.
    rows = await svc.list(wf)
    out = rows[0]
    assert out["status"] == "draft"
    assert "approval" not in out
    ops = [a["op"] for a in await storage.query("audit")]
    assert "approval-expired" in ops
    stored = await storage.get(wf["actions"]["collection"], rec["key"])
    assert "_id" not in stored


async def test_draft_expires_terminally_lazily():
    clock = Clock()
    svc, wf, storage, _ = make_service(clock=clock)
    rec = await draft_ready(svc, wf, storage)
    clock.now += 31 * 86400           # past the 30d draft_ttl
    # go through list(), which uses storage.query() -- that injects "_id"
    # into the record the TTL transition then persists.
    rows = await svc.list(wf)
    out = rows[0]
    assert out["status"] == "expired"
    stored = await storage.get(wf["actions"]["collection"], rec["key"])
    assert "_id" not in stored


async def test_reject_requires_comment_and_is_terminal():
    svc, wf, storage, _ = make_service()
    rec = await draft_ready(svc, wf, storage)
    assert await svc.reject(wf, rec["key"], comment="") == {
        "error": "a rejection comment is required"}
    out = await svc.reject(wf, rec["key"], comment="wrong company")
    assert out["status"] == "rejected"
    assert out["rejected_comment"] == "wrong company"
    # terminal: cannot re-approve or re-reject
    assert (await svc.approve(wf, rec["key"], approved_by="me"))["error"]
    assert (await svc.reject(wf, rec["key"], comment="again"))["error"]


async def test_reject_allowed_from_approved():
    svc, wf, storage, _ = make_service()
    rec = await draft_ready(svc, wf, storage)
    await svc.approve(wf, rec["key"], approved_by="me")
    out = await svc.reject(wf, rec["key"], comment="changed my mind")
    assert out["status"] == "rejected"


# ---------- execute / confirm / supersede ----------


async def approved_action(svc, wf, storage, item_key="itm-1"):
    await seed_item(storage, wf, key=item_key, title=f"Thing {item_key}")
    rec = await svc.start_draft(wf, item_key)
    return await svc.approve(wf, rec["key"], approved_by="me")


async def test_execute_happy_path_merges_updates_and_audits():
    executor = FakeExecutor(execute_result={"confirmation_screenshot": "c.png",
                                            "status": "hostile-ignored"})
    svc, wf, storage, _ = make_service(executor)
    rec = await approved_action(svc, wf, storage)
    out = await svc.execute(wf, rec["key"])
    assert out["status"] == "executed"
    assert out["confirmation_screenshot"] == "c.png"
    assert out["executed_at"] is not None
    assert executor.execute_calls[0]["key"] == rec["key"]
    ops = [a["op"] for a in await storage.query("audit")]
    assert "execute" in ops


async def test_execute_refuses_unapproved_and_already_executed():
    svc, wf, storage, _ = make_service()
    await seed_item(storage, wf)
    rec = await svc.start_draft(wf, "itm-1")
    assert (await svc.execute(wf, rec["key"]))["error"] == "dispatch not approved"
    await svc.approve(wf, rec["key"], approved_by="me")
    await svc.execute(wf, rec["key"])
    assert (await svc.execute(wf, rec["key"]))["error"] == "already executed"


async def test_execute_refuses_on_hash_mismatch():
    svc, wf, storage, _ = make_service()
    rec = await approved_action(svc, wf, storage)
    stored = await storage.get(wf["actions"]["collection"], rec["key"])
    stored["fields"][0]["value"] = "tampered"       # bypasses the API on purpose
    await storage.put(wf["actions"]["collection"], rec["key"], stored)
    out = await svc.execute(wf, rec["key"])
    assert out == {"error": "draft changed since approval; re-approve required"}


async def test_execute_refuses_when_sibling_already_executed():
    svc, wf, storage, _ = make_service()
    rec = await approved_action(svc, wf, storage)
    await storage.put(wf["actions"]["collection"], "act-sib",
                      {"key": "act-sib", "item_key": "itm-1", "status": "submitted",
                       "fields": [], "created_at": 1.0})
    out = await svc.execute(wf, rec["key"])
    assert out == {"error": "thing already has an executed dispatch"}


async def test_execute_blocked_by_precondition():
    executor = FakeExecutor(precondition_msg="posting is gone")
    svc, wf, storage, _ = make_service(executor)
    rec = await approved_action(svc, wf, storage)
    out = await svc.execute(wf, rec["key"])
    assert out == {"error": "precondition failed: posting is gone"}
    assert (await svc.get(wf, rec["key"]))["status"] == "approved"


async def test_execution_failed_lands_in_failed_and_is_reapprovable():
    executor = FakeExecutor(execute_exc=ExecutionFailed("selector missing"))
    svc, wf, storage, _ = make_service(executor)
    rec = await approved_action(svc, wf, storage)
    out = await svc.execute(wf, rec["key"])
    assert out["status"] == "failed"
    assert "selector missing" in out["notes"]
    again = await svc.approve(wf, rec["key"], approved_by="me")
    assert again["status"] == "approved"


async def test_execution_ambiguous_lands_in_possibly_executed():
    executor = FakeExecutor(execute_exc=ExecutionAmbiguous("click failed mid-flight"))
    svc, wf, storage, _ = make_service(executor)
    rec = await approved_action(svc, wf, storage)
    out = await svc.execute(wf, rec["key"])
    assert out["status"] == "possibly_executed"
    # not editable, not approvable, not re-executable
    assert (await svc.update_fields(wf, rec["key"], []))["error"]
    assert (await svc.approve(wf, rec["key"], approved_by="me"))["error"]
    assert (await svc.execute(wf, rec["key"]))["error"]


async def test_unexpected_executor_crash_is_treated_as_ambiguous():
    executor = FakeExecutor(execute_exc=RuntimeError("boom"))
    svc, wf, storage, _ = make_service(executor)
    rec = await approved_action(svc, wf, storage)
    out = await svc.execute(wf, rec["key"])
    assert out["status"] == "possibly_executed"


async def test_confirm_resolves_possibly_executed():
    executor = FakeExecutor(execute_exc=ExecutionAmbiguous("?"))
    svc, wf, storage, _ = make_service(executor)
    rec = await approved_action(svc, wf, storage)
    await svc.execute(wf, rec["key"])
    out = await svc.confirm(wf, rec["key"], outcome="executed")
    assert out["status"] == "executed"
    # confirm only works from possibly_executed
    assert (await svc.confirm(wf, rec["key"], outcome="failed"))["error"]


async def test_confirm_rejects_bad_outcome():
    executor = FakeExecutor(execute_exc=ExecutionAmbiguous("?"))
    svc, wf, storage, _ = make_service(executor)
    rec = await approved_action(svc, wf, storage)
    await svc.execute(wf, rec["key"])
    assert (await svc.confirm(wf, rec["key"], outcome="maybe"))["error"]


async def test_successful_execute_supersedes_open_siblings():
    svc, wf, storage, _ = make_service()
    rec = await approved_action(svc, wf, storage)
    await storage.put(wf["actions"]["collection"], "act-open",
                      {"key": "act-open", "item_key": "itm-1", "status": "draft",
                       "fields": [], "created_at": 1.0})
    await storage.put(wf["actions"]["collection"], "act-done",
                      {"key": "act-done", "item_key": "itm-1", "status": "rejected",
                       "fields": [], "created_at": 1.0})
    await svc.execute(wf, rec["key"])
    assert (await storage.get(wf["actions"]["collection"], "act-open"))["status"] == "superseded"
    assert (await storage.get(wf["actions"]["collection"], "act-done"))["status"] == "rejected"


async def test_concurrent_execute_has_one_winner():
    svc, wf, storage, executor = make_service()
    rec = await approved_action(svc, wf, storage)
    results = await asyncio.gather(svc.execute(wf, rec["key"]),
                                   svc.execute(wf, rec["key"]))
    statuses = sorted(str(r.get("status", r.get("error"))) for r in results)
    assert len(executor.execute_calls) == 1
    assert "executed" in statuses


async def test_sibling_execute_race_single_winner():
    class SlowExecutor(FakeExecutor):
        async def execute(self, record):
            self.execute_calls.append(record)
            await asyncio.sleep(0.05)
            return {}

    executor = SlowExecutor()
    svc, wf, storage, _ = make_service(executor)
    await seed_item(storage, wf)
    rec_a = await svc.start_draft(wf, "itm-1")
    rec_a = await svc.approve(wf, rec_a["key"], approved_by="me")
    rec_b = await svc.start_draft(wf, "itm-1")
    rec_b = await svc.approve(wf, rec_b["key"], approved_by="me")

    results = await asyncio.gather(svc.execute(wf, rec_a["key"]),
                                   svc.execute(wf, rec_b["key"]),
                                   return_exceptions=False)

    executed = [r for r in results if r.get("status") == "executed"]
    errored = [r for r in results if r.get("error")]
    assert len(executed) == 1
    assert len(errored) == 1
    assert errored[0] == {"error": "thing has a dispatch awaiting completion or confirmation"}

    keys = {rec_a["key"], rec_b["key"]}
    executed_keys = {r["key"] for r in executed}
    loser_key = (keys - executed_keys).pop()
    loser_record = await storage.get(wf["actions"]["collection"], loser_key)
    assert loser_record["status"] != "executed"


async def test_possibly_executed_sibling_blocks_execute():
    svc, wf, storage, _ = make_service()
    rec = await approved_action(svc, wf, storage)
    await storage.put(wf["actions"]["collection"], "act-sib",
                      {"key": "act-sib", "item_key": "itm-1",
                       "status": "possibly_executed", "fields": [], "created_at": 1.0})
    out = await svc.execute(wf, rec["key"])
    assert out == {"error": "thing has a dispatch awaiting completion or confirmation"}
    assert (await svc.get(wf, rec["key"]))["status"] == "approved"


async def test_post_success_failure_maps_to_possibly_executed():
    executor = FakeExecutor(execute_result="garbage")
    svc, wf, storage, _ = make_service(executor)
    rec = await approved_action(svc, wf, storage)
    out = await svc.execute(wf, rec["key"])
    assert out["status"] == "possibly_executed"
    assert "post-execution processing failed" in out["notes"]
    stored = await storage.get(wf["actions"]["collection"], rec["key"])
    assert stored == out
    confirmed = await svc.confirm(wf, rec["key"], outcome="executed")
    assert confirmed["status"] == "executed"


async def test_execute_success_reforces_item_ref():
    # A hostile/buggy executor could try to hijack lineage by returning
    # the item_ref_field in its updates dict. The service must re-force it
    # to ensure it never changes.
    executor = FakeExecutor(execute_result={"item_key": "hijacked"})
    svc, wf, storage, _ = make_service(executor)
    rec = await approved_action(svc, wf, storage)
    original_item_key = rec["item_key"]
    out = await svc.execute(wf, rec["key"])
    assert out["status"] == "executed"
    assert out["item_key"] == original_item_key
    stored = await storage.get(wf["actions"]["collection"], rec["key"])
    assert stored["item_key"] == original_item_key


async def test_execute_success_reforces_timestamps():
    # A hostile/buggy executor could try to clobber created_at/updated_at
    # via its updates dict. The service must re-force them, mirroring
    # start_draft's timestamp pinning.
    executor = FakeExecutor(execute_result={"created_at": 9e12, "updated_at": 9e12})
    svc, wf, storage, _ = make_service(executor)
    rec = await approved_action(svc, wf, storage)
    original_created_at = rec["created_at"]
    original_updated_at = rec["updated_at"]
    out = await svc.execute(wf, rec["key"])
    assert out["status"] == "executed"
    assert out["created_at"] == original_created_at
    assert out["updated_at"] == original_updated_at
    stored = await storage.get(wf["actions"]["collection"], rec["key"])
    assert stored["created_at"] == original_created_at
    assert stored["updated_at"] == original_updated_at


async def test_execute_failure_paths_reforce_identity():
    # A hostile/buggy executor could mutate identity fields in place on the
    # record it was handed (it's passed by reference) before raising. The
    # failure handlers must re-force key/item_ref just like the success path
    # does, so a failing executor can never hijack lineage.
    class HijackingExecutor(FakeExecutor):
        def __init__(self, exc):
            super().__init__()
            self.exc = exc

        async def execute(self, record):
            self.execute_calls.append(record)
            record["key"] = "hijacked-key"
            record["item_key"] = "hijacked-item"
            raise self.exc

    # ExecutionFailed -> status "failed", identity intact.
    executor = HijackingExecutor(ExecutionFailed("selector missing"))
    svc, wf, storage, _ = make_service(executor)
    rec = await approved_action(svc, wf, storage)
    original_key, original_item_key = rec["key"], rec["item_key"]
    out = await svc.execute(wf, rec["key"])
    assert out["status"] == "failed"
    assert out["key"] == original_key
    assert out["item_key"] == original_item_key
    stored = await storage.get(wf["actions"]["collection"], original_key)
    assert stored is not None
    assert stored["key"] == original_key
    assert stored["item_key"] == original_item_key
    assert stored["status"] == "failed"

    # Generic unexpected exception -> status "possibly_executed", identity intact.
    executor2 = HijackingExecutor(RuntimeError("boom"))
    svc2, wf2, storage2, _ = make_service(executor2)
    rec2 = await approved_action(svc2, wf2, storage2)
    original_key2, original_item_key2 = rec2["key"], rec2["item_key"]
    out2 = await svc2.execute(wf2, rec2["key"])
    assert out2["status"] == "possibly_executed"
    assert out2["key"] == original_key2
    assert out2["item_key"] == original_item_key2
    stored2 = await storage2.get(wf2["actions"]["collection"], original_key2)
    assert stored2 is not None
    assert stored2["key"] == original_key2
    assert stored2["item_key"] == original_item_key2
    assert stored2["status"] == "possibly_executed"

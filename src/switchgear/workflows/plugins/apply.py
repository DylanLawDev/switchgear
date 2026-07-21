"""SubmitApplicationExecutor: the job-application executor, moved verbatim in
spirit from the old apply/service.py. The fill subagent reads untrusted
third-party pages, so it gets exactly ["browser", "resources"] and no
storage access; the GatedActionService is the sole writer of records. The
browser tool exposes no submit operation — the only path to a real submission
is execute(), which the service invokes only for an approved, hash-verified
record."""

import json

from switchgear.artifacts import is_safe_artifact_filename, resolve_artifact_path
from switchgear.pdf import resume_artifact_dir
from switchgear.workflows.actions import (
    DraftResult,
    ExecutionAmbiguous,
    ExecutionFailed,
    sanitize_field,
)

FILL_TASK_TEMPLATE = """\
Open {apply_url} with the browser tool and fill out this job application form
as completely as you can, grounding every value you enter in facts you can
verify. Do NOT submit the form: never click a submit/apply button, never
press Enter in a field that would submit the form, and never invoke any
operation that finishes the application. Submission is a separate,
human-approved step outside your control — and you have no way to trigger it
even by accident: you have no storage access and no submit operation.

Steps:
1. Use the `browser` tool (`op: "goto"`) to open the URL, then `op: "read"`
   to see the visible form fields (selector, label, current value).
2. For each field, decide its value:
   - Use the `resources` tool for identity/contact/experience facts: call it
     with `op: "read"` and `name: "career-bank"` to load the owner's career
     bank, a json document with "profile" (name/contact/headline), "skills",
     and "experiences" (each experience carries "facts", and every fact has
     an "id"). When a field's value comes straight from the profile, set
     "source" to "profile"; when it comes from a specific career fact, set
     "source" to "fact:<fact_id>" (using that fact's real "id" from the
     json).
   - Use the tailored-resume context given to you (if any) for resume-derived
     fields; set "source" to "resume" in that case.
   - If you must reason your way to a value that isn't grounded in the
     profile, a fact, or the resume context (e.g. a free-text answer you
     composed yourself), set "source" to "agent".
   - If you cannot determine a value at all, or the field requires a human
     judgment call (compensation expectations, sponsorship questions,
     open-ended essays, anything sensitive), still record the field but set
     "needs_you" to true and leave "value" as your best guess or "".
   - Set "kind" to "file" for file-upload fields (e.g. a resume/CV upload),
     otherwise "text". For a "file" field, "value" should be the tailored
     resume artifact's filename from the context given to you (e.g. its
     html_file or pdf_file) — if no such artifact filename is available, set
     "needs_you" to true instead of guessing a filename.
   - Fill the field on the page with the `browser` tool's `op: "fill"` only
     for text fields you are confident about (this does not submit anything;
     filling in a text box is safe). Never attempt to upload a file
     yourself — just record "kind": "file" and the artifact filename; the
     actual upload happens later, outside your control.
3. If you hit a CAPTCHA or a login wall you cannot get past, stop trying to
   fill further fields and say so plainly in your reply's "notes" (e.g.
   "CAPTCHA blocked automated fill" or "login required").
4. Take a screenshot of the form as you left it with the `browser` tool
   (`op: "screenshot"`); its response is `{{"file": "<filename>"}}` — put
   that filename in your reply's "screenshot" field (or null if you never
   captured one).
5. Finish by replying with ONLY a JSON object — no prose, no markdown code
   fences — of exactly this shape:
   {{"fields": [{{"selector": str, "label": str, "value": str,
   "source": str, "needs_you": bool, "kind": "text"|"file"}}, ...],
   "notes": str, "screenshot": str|null}}
   List one field entry per field you reasoned about, in the order they
   appear on the page. Put anything the human should know in "notes"
   (CAPTCHAs, login walls, fields you could not map, anything unusual); use
   "" if there is nothing to flag. You cannot write the application record
   yourself — the caller reads this JSON reply and writes the record for
   you, so nothing you say here can change the application's status.
"""


def _parse_fill_result(raw_text: str) -> tuple[list[dict], str, str | None, str | None]:
    """Parse the fill subagent's JSON reply.

    Returns (fields, notes, screenshot, error). On any parse failure the
    caller gets an empty field list and an explanatory note instead of a
    crash; top-level keys other than "fields"/"notes"/"screenshot" (e.g. a
    hostile "status") are silently ignored — they are never read.
    """
    text = (raw_text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None

    if not isinstance(parsed, dict):
        return (
            [], "the fill subagent's result could not be parsed as JSON — "
            "review the application manually.", None,
            "fill subagent did not return a parseable JSON result",
        )

    fields = []
    for raw_field in parsed.get("fields") or []:
        sanitized = sanitize_field(raw_field)
        if sanitized is not None:
            fields.append(sanitized)

    notes = parsed.get("notes")
    notes = str(notes) if notes is not None else ""

    screenshot = parsed.get("screenshot")
    if screenshot is not None:
        screenshot = str(screenshot)
        if not is_safe_artifact_filename(screenshot):
            screenshot = None

    return fields, notes, screenshot, None


class SubmitApplicationExecutor:
    def __init__(self, storage, browser_manager, registry, settings):
        self._db = storage
        self._browser = browser_manager
        self._registry = registry
        self._s = settings

    async def _resume_context(self, job_key: str) -> str | None:
        resumes = await self._db.query("resumes", where={"job_key": job_key})
        if not resumes:
            return None
        resumes.sort(key=lambda r: r.get("created_at") or 0, reverse=True)
        latest = resumes[0]
        return (
            f"A tailored resume already exists for this job: rid={latest.get('rid')}, "
            f"keyword_report={latest.get('keyword_report')}, "
            f"html_file={latest.get('html_file')}."
        )

    async def draft(self, item: dict) -> DraftResult:
        apply_url = item.get("url")
        context = await self._resume_context(item.get("key"))
        raw = await self._registry.execute("spawn_subagent", {
            "task": FILL_TASK_TEMPLATE.format(apply_url=apply_url),
            "tools": ["browser", "resources"],
            "context": context,
        })
        subagent = json.loads(raw)
        fields, notes, screenshot, parse_error = _parse_fill_result(
            subagent.get("result") or "")
        error = subagent.get("error") or parse_error
        return DraftResult(
            fields=fields, notes=notes, error=error,
            extra={"job_title": item.get("title"), "company": item.get("company"),
                   "apply_url": apply_url, "screenshot": screenshot,
                   "confirmation_screenshot": None})

    async def execute(self, record: dict) -> dict:
        try:
            # A fresh session, not whatever the fill subagent left open: the
            # owner has since reviewed/edited values, and replaying from the
            # stored record is simpler to reason about than live state.
            await self._browser.reset()
            session = await self._browser.session()
            await session.goto(record["apply_url"])
            for field in record.get("fields", []):
                if field.get("needs_you"):
                    continue
                if field.get("kind") == "file":
                    filename = field.get("value") or ""
                    if not filename or not is_safe_artifact_filename(filename):
                        raise ValueError(
                            f"field {field.get('selector')!r}: missing or "
                            f"unsafe file value {filename!r}")
                    path = resolve_artifact_path(resume_artifact_dir(self._s), filename)
                    if not path.is_file():
                        raise ValueError(
                            f"field {field.get('selector')!r}: resume "
                            f"artifact not found: {filename!r}")
                    await session.upload(field["selector"], str(path))
                else:
                    await session.fill(field["selector"], field["value"])
        except Exception as e:
            # Nothing was submitted yet: safe to re-approve and retry.
            raise ExecutionFailed(f"{type(e).__name__}: {e}") from e

        try:
            await session.submit_form()
        except Exception as e:
            # The click may have landed on the far side before raising.
            raise ExecutionAmbiguous(
                "submit click failed mid-flight — verify with the employer "
                f"before confirming ({type(e).__name__}: {e})") from e

        key = record.get("key") or record.get("app_id")
        try:
            shot_path = str(self._browser.screenshot_dir / f"confirm-{key}.png")
            await session.screenshot(shot_path)
        except Exception as e:
            note = f"confirmation screenshot failed: {type(e).__name__}: {e}"
            existing = record.get("notes") or ""
            return {"confirmation_screenshot": None,
                    "notes": f"{existing}\n{note}".strip() if existing else note}
        return {"confirmation_screenshot": f"confirm-{key}.png"}

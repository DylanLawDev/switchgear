from switchgear.tools.base import Tool


def _summarize(result: dict) -> dict:
    if "error" in result:
        return result
    selection = result.get("selection") or {}
    bullets = 0
    rephrased = 0
    for section in selection.get("sections") or []:
        for entry in section.get("entries") or []:
            for bullet in entry.get("bullets") or []:
                bullets += 1
                if bullet.get("rephrased"):
                    rephrased += 1
    return {
        "ok": result.get("ok", True),
        "rid": result.get("rid"),
        "job_title": result.get("job_title"),
        "company": result.get("company"),
        "bullets": bullets,
        "rephrased": rephrased,
        "keyword_report": result.get("keyword_report"),
        "files": {"html": result.get("html_file"), "pdf": result.get("pdf_file")},
    }


def make_tailor_resume_tool(pipeline) -> Tool:
    async def _tailor(job_key: str):
        result = await pipeline.tailor(job_key)
        return _summarize(result)

    return Tool(
        name="tailor_resume",
        description=("Tailor a resume for a specific job from the owner's career bank. "
                     "Grounded: every bullet cites a fact_id from the career bank; nothing "
                     "is invented. Writes an HTML artifact (and a PDF when a PDF backend is "
                     "configured) and returns a summary — bullet/rephrased counts, JD "
                     "keyword coverage, and file names — not the full resume text."),
        parameters={"type": "object", "properties": {
            "job_key": {"type": "string"}}, "required": ["job_key"]},
        handler=_tailor,
    )

"""Grounded resume tailoring pipeline: select facts, render, persist artifacts."""

import time
from uuid import uuid4

from switchgear.pdf import resume_artifact_dir
from switchgear.resume.render import keyword_report, render_html
from switchgear.resume.tailor import TailorError, tailor_selection


class TailorPipeline:
    def __init__(self, gateway, storage, bank_provider, renderer, settings):
        self.gateway = gateway
        self.storage = storage
        self.bank_provider = bank_provider
        self.renderer = renderer
        self.settings = settings

    async def tailor(self, job_key: str) -> dict:
        bank = await self.bank_provider()
        if bank is None:
            return {"error": "career bank unavailable"}

        job = await self.storage.get("jobs", job_key)
        if job is None:
            return {"error": "job not found"}

        try:
            selection = await tailor_selection(self.gateway, job, bank)
        except TailorError as e:
            return {"error": f"tailoring failed: {e}"}

        html = render_html(bank.profile, selection)
        report = keyword_report(job.get("description") or "", selection, bank)

        rid = f"resume-{job_key[:12]}-{uuid4().hex[:8]}"
        artifact_dir = resume_artifact_dir(self.settings)
        (artifact_dir / f"{rid}.html").write_text(html, encoding="utf-8")

        pdf_result = await self.renderer.render_pdf(html, str(artifact_dir / f"{rid}.pdf"))
        pdf_file = f"{rid}.pdf" if pdf_result else None

        record = {
            "rid": rid,
            "job_key": job_key,
            "job_title": job.get("title"),
            "company": job.get("company"),
            "wording_changes": selection.pop("wording_changes", []),
            "selection": selection,
            "keyword_report": report,
            "html_file": f"{rid}.html",
            "pdf_file": pdf_file,
            "created_at": time.time(),
        }
        await self.storage.put("resumes", rid, record)
        return {"ok": True, **record}

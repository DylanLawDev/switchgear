// Transcribed from workflows/job-hunt/WORKFLOW.md, run through model.py's parse_workflow +
// workflow_routes.public_definition() defaults. Verified against the real backend:
//   uv run python -c "
//     from switchgear.workflows.model import parse_workflow
//     from switchgear.web.workflow_routes import public_definition
//     wf = parse_workflow(open('workflows/job-hunt/WORKFLOW.md').read(),
//                          generators={'tailor-resume'}, executors={'submit-application'})
//     wf['status'] = 'active'
//     import json; print(json.dumps(public_definition(wf), indent=2))"
// (task-7-report.md carries the full transcript). Keep in sync if WORKFLOW.md changes.
import { WorkflowDefinition } from "../../api/types";

export const jobHuntDefinition: WorkflowDefinition = {
  name: "job-hunt",
  description: "Find, score, and apply to jobs",
  body:
    "Finds new postings daily via the job-search skill, scores them against the\n" +
    "career bank, and — on request — tailors a resume and drafts the application\n" +
    "form. Submissions require explicit approval here; nothing is ever sent\n" +
    "without it.\n",
  items: {
    label: "job",
    label_plural: "jobs",
    collection: "jobs",
    key_field: "key",
    title_field: "title",
    fields: {
      title: { type: "text" },
      company: { type: "text" },
      location: { type: "text" },
      source: { type: "text" },
      score: { type: "score", max: 100 },
      rationale: { type: "markdown" },
      url: { type: "url" },
      first_seen: { type: "timestamp" },
    },
    list_fields: ["title", "company", "location", "source", "score", "first_seen"],
    detail_fields: null,
    sort: ["-score", "-first_seen"],
    expected_update_period: 172800,
    retention: null,
  },
  artifacts: {
    label: "resume",
    label_plural: "resumes",
    collection: "resumes",
    key_field: "rid",
    title_field: "job_title",
    item_ref_field: "job_key",
    fields: {
      job_title: { type: "text" },
      company: { type: "text" },
      created_at: { type: "timestamp" },
      html_file: { type: "artifact", href_prefix: "/resumes/" },
      pdf_file: { type: "artifact", href_prefix: "/resumes/" },
      keyword_report: { type: "json" },
    },
    list_fields: ["job_title", "company", "created_at", "html_file", "pdf_file"],
    detail_fields: null,
    sort: ["-created_at"],
    expected_update_period: null,
    retention: null,
  },
  actions: {
    label: "application",
    label_plural: "applications",
    collection: "applications",
    key_field: "app_id",
    item_ref_field: "job_key",
    executor: "submit-application",
    approval_ttl: 604800,
    draft_ttl: 2592000,
  },
  generate: { plugin: "tailor-resume", label: "Tailor resume" },
  intake: { skills: ["job-search"] },
};

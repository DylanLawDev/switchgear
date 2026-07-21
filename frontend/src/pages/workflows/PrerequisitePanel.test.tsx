import { http, HttpResponse } from "msw";
import { screen, within } from "@testing-library/react";
import { server } from "../../test/msw";
import { renderWithProviders } from "../../test/utils";
import { ResourceSummary, SkillRun, WorkflowDefinition } from "../../api/types";
import { jobHuntDefinition } from "../../test/fixtures/jobHuntDefinition";
import PrerequisitePanel from "./PrerequisitePanel";
import ItemsSection from "./ItemsSection";

const careerBankSummary: ResourceSummary = {
  name: "career-bank", kind: "json", description: "bank", size: 20, source: "user", updated_at: 1_700_000_000,
};

function mockPanel(opts: { resources?: ResourceSummary[]; runs?: SkillRun[] } = {}) {
  server.use(
    http.get("/api/resources", () => HttpResponse.json(opts.resources ?? [])),
    http.get("/api/skills/job-search/runs", () => HttpResponse.json(opts.runs ?? [])),
  );
}

// ---------- career check ----------

test("career check passes with a ✓ chip when a career-bank resource exists", async () => {
  mockPanel({ resources: [careerBankSummary] });
  renderWithProviders(<PrerequisitePanel />);

  const row = (await screen.findByText("career bank on file")).closest("li")!;
  expect(within(row).getByText("✓")).toBeInTheDocument();
});

test("career check fails and links to /resources when no career-bank resource exists", async () => {
  mockPanel({ resources: [] });
  renderWithProviders(<PrerequisitePanel />);

  expect(await screen.findByText(/add your career bank/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "resources" })).toHaveAttribute("href", "/resources");
});

test("career check shows a distinct 'couldn't check' copy (not the add-it copy) when the resources query errors", async () => {
  mockPanel({ runs: [] });
  server.use(http.get("/api/resources", () => new HttpResponse(null, { status: 500 })));
  renderWithProviders(<PrerequisitePanel />);

  expect(await screen.findByText("couldn't check — retry")).toBeInTheDocument();
  expect(screen.queryByText(/add your career bank/i)).not.toBeInTheDocument();
});

// ---------- JSearch check ----------

test("JSearch check: no runs yet shows the not-yet-verified copy", async () => {
  mockPanel({ runs: [] });
  renderWithProviders(<PrerequisitePanel />);

  expect(
    await screen.findByText("not yet verified — run the job-search skill from /skills to check"),
  ).toBeInTheDocument();
});

test("JSearch check: latest run failed with the API key error shows the failure copy plus the error text", async () => {
  // Backend sorts runs desc by `at` — index 0 is the latest.
  mockPanel({
    runs: [
      { skill: "job-search", ok: false, at: 2, error: "SWITCHGEAR_JSEARCH_API_KEY missing" },
      { skill: "job-search", ok: true, at: 1 },
    ],
  });
  renderWithProviders(<PrerequisitePanel />);

  expect(
    await screen.findByText(/intake ran and failed — check SWITCHGEAR_JSEARCH_API_KEY in the deploy env/),
  ).toBeInTheDocument();
  expect(screen.getByText(/SWITCHGEAR_JSEARCH_API_KEY missing/)).toBeInTheDocument();
});

test("JSearch check passes with a ✓ chip when the latest run is ok", async () => {
  mockPanel({ runs: [{ skill: "job-search", ok: true, at: 5 }] });
  renderWithProviders(<PrerequisitePanel />);

  const row = (await screen.findByText("job-search intake verified")).closest("li")!;
  expect(within(row).getByText("✓")).toBeInTheDocument();
});

test("JSearch check degrades to not-yet-verified when the runs query errors (no double toast)", async () => {
  mockPanel({ resources: [careerBankSummary] });
  server.use(http.get("/api/skills/job-search/runs", () => new HttpResponse(null, { status: 500 })));
  renderWithProviders(<PrerequisitePanel />);

  expect(
    await screen.findByText("not yet verified — run the job-search skill from /skills to check"),
  ).toBeInTheDocument();
});

// ---------- ItemsSection wiring ----------

const researchDefinition: WorkflowDefinition = {
  name: "research",
  description: "Daily research digest",
  body: "",
  items: {
    label: "entry", label_plural: "entries", collection: "entries", key_field: "key", title_field: "subject",
    fields: { subject: { type: "text" } }, list_fields: ["subject"], detail_fields: null, sort: [],
    expected_update_period: null, retention: null,
  },
  artifacts: null,
  actions: null,
  generate: null,
  intake: { skills: ["research-watch"] },
};

test("job-hunt with empty items renders the PrerequisitePanel, not the plain empty state", async () => {
  mockPanel({ resources: [] });
  server.use(
    http.get("/api/workflows/job-hunt/items", () => HttpResponse.json([])),
  );
  renderWithProviders(
    <ItemsSection workflowName="job-hunt" definition={jobHuntDefinition} selectedKey={null} onSelect={() => {}} />,
  );

  expect(await screen.findByText(/add your career bank/i)).toBeInTheDocument();
  expect(screen.queryByText("no jobs yet")).not.toBeInTheDocument();
});

test("a non-job-hunt workflow with empty items renders a plain empty state with an intake hint, no panel", async () => {
  server.use(
    http.get("/api/workflows/research/items", () => HttpResponse.json([])),
  );
  renderWithProviders(
    <ItemsSection workflowName="research" definition={researchDefinition} selectedKey={null} onSelect={() => {}} />,
  );

  expect(await screen.findByText("no entries yet")).toBeInTheDocument();
  expect(screen.getByText(/populated by the research-watch skill/)).toBeInTheDocument();
  expect(screen.queryByText(/career bank/i)).not.toBeInTheDocument();
});

import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../test/msw";
import { renderWithProviders } from "../test/utils";
import { jobHuntDefinition } from "../test/fixtures/jobHuntDefinition";
import { WorkflowDefinition, WorkflowSummary } from "../api/types";
import WorkflowsPage from "./WorkflowsPage";
import RunsView from "./workflows/RunsView";
import styles from "./workflows/workflows.module.css";

// A second, minimal rail workflow (no artifacts/actions/generate) — exercises the
// conditional-section branches (ItemsSection only, no Generate/Draft buttons). It also
// carries NO `ui_home` key, exercising the SPEC §5.4 default (absent ⇒ "workflows").
const researchDefinition: WorkflowDefinition = {
  name: "research",
  description: "Daily research digest",
  body: "",
  items: {
    label: "entry",
    label_plural: "entries",
    collection: "entries",
    key_field: "key",
    title_field: "subject",
    fields: { subject: { type: "text" } },
    list_fields: ["subject"],
    detail_fields: null,
    sort: [],
    expected_update_period: null,
    retention: null,
  },
  artifacts: null,
  actions: null,
  generate: null,
};

// Three workflows exercising railWorkflows' ui_home filtering + defaulting (SPEC §5.4):
// job-hunt declares ui_home:"workflows" (and is stale); channel-email declares
// ui_home:"channels" (must NOT show in the workflows rail); research has no ui_home key
// at all (must default to "workflows" and still show in the rail).
const summaries: WorkflowSummary[] = [
  { name: "job-hunt", description: "Find, score, and apply to jobs", status: "active", stale: true, ui_home: "workflows" },
  { name: "channel-email", description: "Email intake channel", status: "active", stale: false, ui_home: "channels" },
  { name: "research", description: "Daily research digest", status: "active", stale: false },
];

const job1 = {
  key: "j1",
  title: "Foo Corp SWE",
  company: "Foo Corp",
  location: "Remote",
  source: "job-search",
  score: 82,
  rationale: "**Good** fit",
  url: "https://foo.dev/apply",
  first_seen: 1_700_000_000,
  bespoke_note: "manually flagged", // undeclared key — exercises RawDetails
};
const job2 = { key: "j2", title: "Bar Inc SRE", company: "Bar Inc", location: "NYC", source: "referral", score: 40, rationale: "", url: "", first_seen: 1_699_000_000 };

const resume1 = {
  rid: "r1",
  job_title: "Foo Corp SWE",
  company: "Foo Corp",
  created_at: 1_700_000_100,
  html_file: "resume.html",
  pdf_file: "resume.pdf",
  keyword_report: { matched: 4 },
  job_key: "j1",
};

const researchEntries = [{ key: "d1", subject: "hello" }];

function mockWorkflows() {
  server.use(
    http.get("/api/workflows", () => HttpResponse.json(summaries)),
    http.get("/api/workflows/:name", ({ params }) =>
      params.name === "job-hunt" ? HttpResponse.json(jobHuntDefinition) : HttpResponse.json(researchDefinition),
    ),
    http.get("/api/workflows/:name/actions", () => HttpResponse.json([])),
    http.get("/api/workflows/:name/items", ({ params }) =>
      HttpResponse.json(params.name === "job-hunt" ? [job1, job2] : researchEntries),
    ),
    http.get("/api/workflows/job-hunt/items/:key", ({ params }) =>
      HttpResponse.json({
        record: params.key === "j1" ? job1 : job2,
        artifacts: params.key === "j1" ? [resume1] : [],
        actions: [],
      }),
    ),
    http.get("/api/workflows/job-hunt/artifacts", () => HttpResponse.json([resume1])),
    http.get("/api/workflows/job-hunt/artifacts/:rid", () =>
      HttpResponse.json({ record: resume1, item: { key: "j1", title: "Foo Corp SWE" } }),
    ),
    http.post("/api/workflows/job-hunt/items/:key/generate", () => HttpResponse.json({ ok: true })),
  );
}

test("with no :name param, renders the rail plus an empty-state placeholder", async () => {
  mockWorkflows();
  renderWithProviders(<WorkflowsPage />, { route: "/workflows", path: "/workflows" });
  expect(await screen.findByRole("link", { name: /job-hunt/ })).toBeInTheDocument();
  expect(await screen.findByText(/pick a workflow/i)).toBeInTheDocument();
});

test("rail shows ui_home:workflows and ui_home-absent workflows, excludes ui_home:channels", async () => {
  mockWorkflows();
  renderWithProviders(<WorkflowsPage />, { route: "/workflows", path: "/workflows" });
  expect(await screen.findByRole("link", { name: /job-hunt/ })).toBeInTheDocument();
  // research has no `ui_home` key at all — must default to "workflows" (SPEC §5.4) and show.
  expect(await screen.findByRole("link", { name: /research/ })).toBeInTheDocument();
  // channel-email declares ui_home:"channels" — must NOT show in the workflows rail.
  expect(screen.queryByRole("link", { name: /channel-email/ })).not.toBeInTheDocument();
});

test("selecting a workflow renders its header, description, and items table", async () => {
  mockWorkflows();
  renderWithProviders(<WorkflowsPage />, { route: "/workflows/job-hunt", path: "/workflows/:name" });
  expect(await screen.findByRole("heading", { name: "job-hunt" })).toBeInTheDocument();
  const pane = document.querySelector(`.${styles.pane}`) as HTMLElement;
  expect(within(pane).getByText(/Find, score, and apply to jobs/)).toBeInTheDocument();
  expect(await screen.findByRole("cell", { name: "Foo Corp SWE" })).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "Bar Inc SRE" })).toBeInTheDocument();
});

test("clicking an item row opens its detail with declared fields, raw json, and a generate button", async () => {
  mockWorkflows();
  const user = userEvent.setup();
  renderWithProviders(<WorkflowsPage />, { route: "/workflows/job-hunt", path: "/workflows/:name" });

  const row = (await screen.findByText("Foo Corp SWE")).closest("tr")!;
  await user.click(row);

  expect(await screen.findByRole("heading", { name: "Foo Corp SWE" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Tailor resume" })).toBeInTheDocument();
  // Draft is wired (Task 8) — always enabled (server re-checks the transition); no ConfirmDialog gate.
  expect(screen.getByRole("button", { name: "Draft application" })).toBeEnabled();

  const raw = screen.getByText("raw").closest("details")!;
  expect(within(raw).getByText(/bespoke_note/)).toBeInTheDocument();
});

test("generate posts to the item's generate endpoint and shows the inline result", async () => {
  mockWorkflows();
  const user = userEvent.setup();
  renderWithProviders(<WorkflowsPage />, { route: "/workflows/job-hunt", path: "/workflows/:name" });

  await user.click((await screen.findByText("Foo Corp SWE")).closest("tr")!);
  await user.click(await screen.findByRole("button", { name: "Tailor resume" }));

  expect(await screen.findByText("done")).toBeInTheDocument();
});

test("artifacts table renders and clicking a row opens artifact detail naming its parent item", async () => {
  mockWorkflows();
  const user = userEvent.setup();
  renderWithProviders(<WorkflowsPage />, { route: "/workflows/job-hunt", path: "/workflows/:name" });

  const artifactRow = (await screen.findByText("resume.html")).closest("tr")!;
  await user.click(artifactRow);

  expect(await screen.findByRole("heading", { name: "Foo Corp SWE" })).toBeInTheDocument();
  expect(await screen.findByText("for Foo Corp SWE")).toBeInTheDocument();
});

test("clicking a resume in the item detail's mini-list selects and shows that artifact below", async () => {
  mockWorkflows();
  const user = userEvent.setup();
  renderWithProviders(<WorkflowsPage />, { route: "/workflows/job-hunt", path: "/workflows/:name" });

  await user.click((await screen.findByText("Foo Corp SWE")).closest("tr")!);
  await user.click(await screen.findByRole("button", { name: "Foo Corp SWE" })); // mini-list row

  await waitFor(() => {
    expect(screen.getByText("for Foo Corp SWE")).toBeInTheDocument();
  });
});

// Exercises RunsView directly (rather than driving it via a rail-link click through
// WorkflowsPage's data router): jsdom's AbortController and Node/undici's global fetch
// disagree on the AbortSignal realm the instant a data router performs any client-side
// navigation (react-router's createClientSideRequest constructs `new Request({signal})`),
// throwing "Expected signal to be an instance of AbortSignal" — a jsdom/undici/msw
// environment incompatibility, not a defect in this component. RunsView takes
// `workflowName` as a plain prop and touches no router API itself, so a rerender with a
// new prop reproduces the real "switch workflows" effect (RunsView's own useEffect) without
// tripping that landmine.
test("switching the workflowName prop resets the selected item/artifact and swaps sections", async () => {
  mockWorkflows();
  const user = userEvent.setup();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const { rerender } = render(
    <QueryClientProvider client={qc}>
      <RunsView workflowName="job-hunt" />
    </QueryClientProvider>,
  );

  await user.click((await screen.findByText("Foo Corp SWE")).closest("tr")!);
  expect(await screen.findByRole("heading", { name: "Foo Corp SWE" })).toBeInTheDocument();

  rerender(
    <QueryClientProvider client={qc}>
      <RunsView workflowName="research" />
    </QueryClientProvider>,
  );

  expect(await screen.findByRole("heading", { name: "research" })).toBeInTheDocument();
  expect(await screen.findByText("hello")).toBeInTheDocument();
  // research has no artifacts/actions/generate block — no leftover job-hunt detail or artifacts section
  expect(screen.queryByRole("heading", { name: "Foo Corp SWE" })).not.toBeInTheDocument();
  expect(screen.queryByText(/resumes/i)).not.toBeInTheDocument();
});

// Regression for the PrerequisitePanel query-flash bug: ItemsSection must not mount the
// panel (or fire its useResources/useSkillRuns queries) while /items is still pending, even
// for a workflow whose items eventually resolve non-empty — it must render nothing until
// the query settles, not treat the still-loading `undefined` as "empty".
test("job-hunt items still loading: no PrerequisitePanel flash before the (non-empty) response resolves", async () => {
  mockWorkflows();
  let resolveItems!: (value: Record<string, unknown>[]) => void;
  const deferred = new Promise<Record<string, unknown>[]>((resolve) => {
    resolveItems = resolve;
  });
  server.use(
    http.get("/api/workflows/job-hunt/items", async () => HttpResponse.json(await deferred)),
  );

  renderWithProviders(<WorkflowsPage />, { route: "/workflows/job-hunt", path: "/workflows/:name" });

  await screen.findByRole("heading", { name: "job-hunt" });
  expect(screen.queryByText(/needs two things/)).not.toBeInTheDocument();
  expect(screen.queryByText(/no jobs yet/)).not.toBeInTheDocument();

  resolveItems([job1, job2]);

  expect(await screen.findByRole("cell", { name: "Foo Corp SWE" })).toBeInTheDocument();
  expect(screen.queryByText(/needs two things/)).not.toBeInTheDocument();
});

import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { server } from "../../test/msw";
import { renderWithProviders } from "../../test/utils";
import { jobHuntDefinition } from "../../test/fixtures/jobHuntDefinition";
import { Skill } from "../../api/types";
import DefinitionView from "./DefinitionView";
import WorkflowsPage from "../WorkflowsPage";

const jobHuntNoIntake = { ...jobHuntDefinition };
delete jobHuntNoIntake.intake;

const jobSearchSkill: Skill = {
  name: "job-search",
  description: "Finds postings",
  status: "active",
  source: "repo",
  schedule: "0 6 * * *",
};

function mockSkills(skills: Skill[] = [jobSearchSkill]) {
  server.use(http.get("/api/skills", () => HttpResponse.json(skills)));
}

function mockDefinition(def = jobHuntDefinition) {
  server.use(http.get("/api/workflows/job-hunt", () => HttpResponse.json(def)));
}

test("About renders description and body through the markdown renderer", async () => {
  mockDefinition();
  mockSkills();
  renderWithProviders(<DefinitionView workflowName="job-hunt" />);

  expect(await screen.findByText("Find, score, and apply to jobs")).toBeInTheDocument();
  expect(await screen.findByText(/Finds new postings daily via the job-search skill/)).toBeInTheDocument();
});

// Items and Artifacts schema sections each carry their own field/type/extras table plus a
// "list fields" chip row that repeats several of the same field names — every assertion below
// is scoped to its own section container (found via the section heading) rather than relying
// on document order, so it can't silently drift onto the wrong section.
async function findSchemaSection(heading: string) {
  return (await screen.findByRole("heading", { name: heading })).closest("section")!;
}

test("Items schema table renders field/type/extras rows plus list_fields, sort, and retention chips", async () => {
  mockDefinition();
  mockSkills();
  renderWithProviders(<DefinitionView workflowName="job-hunt" />);

  const items = await findSchemaSection("Items schema");

  // "score" is a genuine items field (fields.score = {type: "score", max: 100}) — real Items
  // content, not borrowed from Artifacts. Both the name and type cells read "score", hence
  // getAllByText — [0] is the name cell (DOM order within the row), either gets us to the row.
  const scoreRow = within(items).getAllByText("score", { selector: "td" })[0].closest("tr")!;
  expect(within(scoreRow).getByText("max 100")).toBeInTheDocument();

  const listFieldsRow = within(items).getByText("list fields").parentElement!;
  expect(within(listFieldsRow).getByText("title")).toBeInTheDocument();
  expect(within(items).getByText("-score")).toBeInTheDocument(); // sort chip
  expect(within(items).getByText(/refresh 2d/)).toBeInTheDocument(); // expected_update_period 172800s

  // html_file/pdf_file are NOT items fields — the job-hunt fixture only declares them under
  // artifacts.fields (asserted in the Artifacts schema test below).
  expect(within(items).queryByText("html_file")).not.toBeInTheDocument();
});

test("Artifacts schema renders when the definition declares artifacts", async () => {
  mockDefinition();
  mockSkills();
  renderWithProviders(<DefinitionView workflowName="job-hunt" />);

  const artifacts = await findSchemaSection("Artifacts schema");

  const htmlFileRow = within(artifacts).getByText("html_file", { selector: "td" }).closest("tr")!;
  expect(within(htmlFileRow).getByText("artifact")).toBeInTheDocument();
  expect(within(htmlFileRow).getByText("/resumes/")).toBeInTheDocument();

  const pdfRow = within(artifacts).getByText("pdf_file", { selector: "td" }).closest("tr")!;
  expect(within(pdfRow).getByText("/resumes/")).toBeInTheDocument();
});

test("Actions card renders the executor, humanized ttls, and the gate diagram", async () => {
  mockDefinition();
  mockSkills();
  renderWithProviders(<DefinitionView workflowName="job-hunt" />);

  expect(await screen.findByText("executor: submit-application")).toBeInTheDocument();
  expect(screen.getByText(/approval ttl 7d/)).toBeInTheDocument();
  expect(screen.getByText(/draft ttl 30d/)).toBeInTheDocument();
  expect(screen.getByText(/draft → approve → execute → confirm/)).toBeInTheDocument();
});

test("Generate chip shows the plugin and label when generate is present", async () => {
  mockDefinition();
  mockSkills();
  renderWithProviders(<DefinitionView workflowName="job-hunt" />);

  expect(await screen.findByText(/tailor-resume/)).toBeInTheDocument();
});

test("Intake section renders skill cron chips when intake is present and skills carry a schedule", async () => {
  mockDefinition();
  mockSkills();
  renderWithProviders(<DefinitionView workflowName="job-hunt" />);

  expect(await screen.findByRole("heading", { name: "Intake" })).toBeInTheDocument();
  expect(screen.getByText("job-search")).toBeInTheDocument();
  expect(screen.getByText("0 6 * * *")).toBeInTheDocument();
});

test("Intake section is absent when the definition omits the intake key (SPEC §5.4.2 tolerance)", async () => {
  mockDefinition(jobHuntNoIntake);
  mockSkills();
  renderWithProviders(<DefinitionView workflowName="job-hunt" />);

  await screen.findByRole("heading", { name: "Items schema" }); // definition has loaded
  expect(screen.queryByRole("heading", { name: "Intake" })).not.toBeInTheDocument();
});

// ---------- Runs <-> Definition toggle (WorkflowsPage) ----------

function mockWorkflowsPage() {
  server.use(
    http.get("/api/workflows", () =>
      HttpResponse.json([{ name: "job-hunt", description: "Find, score, and apply to jobs", status: "active", stale: false, ui_home: "workflows" }]),
    ),
    http.get("/api/workflows/job-hunt", () => HttpResponse.json(jobHuntDefinition)),
    http.get("/api/workflows/job-hunt/items", () => HttpResponse.json([])),
    http.get("/api/workflows/job-hunt/artifacts", () => HttpResponse.json([])),
    http.get("/api/workflows/job-hunt/actions", () => HttpResponse.json([])),
    http.get("/api/skills", () => HttpResponse.json([jobSearchSkill])),
    // job-hunt's items list above is empty — RunsView's ItemsSection renders the
    // PrerequisitePanel (SPEC §5.8) for that case, which needs these two.
    http.get("/api/resources", () => HttpResponse.json([])),
    http.get("/api/skills/job-search/runs", () => HttpResponse.json([])),
  );
}

function renderWorkflowsWithRouter(route: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter([{ path: "/workflows/:name", element: <WorkflowsPage /> }], {
    initialEntries: [route],
  });
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

test("?view=definition renders DefinitionView instead of RunsView", async () => {
  mockWorkflowsPage();
  renderWorkflowsWithRouter("/workflows/job-hunt?view=definition");

  expect(await screen.findByRole("heading", { name: "Items schema" })).toBeInTheDocument();
});

test("toggling to Definition updates the URL, and the back button restores Runs", async () => {
  mockWorkflowsPage();
  const user = userEvent.setup();
  const router = renderWorkflowsWithRouter("/workflows/job-hunt");

  expect(await screen.findByRole("heading", { name: "job-hunt" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Items schema" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: "Definition" }));

  expect(await screen.findByRole("heading", { name: "Items schema" })).toBeInTheDocument();
  expect(router.state.location.search).toBe("?view=definition");

  await act(async () => {
    router.navigate(-1);
  });

  await screen.findByRole("tab", { name: "Runs", selected: true });
  expect(screen.queryByRole("heading", { name: "Items schema" })).not.toBeInTheDocument();
  expect(router.state.location.search).toBe("");
});

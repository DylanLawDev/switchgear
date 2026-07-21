import { http, HttpResponse } from "msw";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, Link, RouterProvider } from "react-router-dom";
import { server } from "../../test/msw";
import { renderWithProviders } from "../../test/utils";
import { groupResources } from "../../api/queries/resources";
import { toast } from "../../components/Toaster";
import { ResourceSummary } from "../../api/types";
import ResourcesPage from "../ResourcesPage";

const careerBankSummary: ResourceSummary = {
  name: "career-bank", kind: "json", description: "bank", size: 20, source: "user", updated_at: 1700000000,
};
const careerProfileSummary: ResourceSummary = {
  name: "career-profile", kind: "md", description: "profile", size: 5, source: "seed", updated_at: 1700000000,
};
const userNoteSummary: ResourceSummary = {
  name: "notes", kind: "txt", description: "notes", size: 5, source: "user", updated_at: 1700000000,
};
const agentDraftSummary: ResourceSummary = {
  name: "agent-draft", kind: "txt", description: "", size: 5, source: "agent", updated_at: 1700000000,
};
const seedFaqSummary: ResourceSummary = {
  name: "faq", kind: "txt", description: "", size: 5, source: "seed", updated_at: 1700000000,
};

const careerBankDoc = {
  name: "career-bank", kind: "json", description: "bank", content: "{}",
  size: 2, source: "user", created_at: 1700000000, updated_at: 1700000000,
};

function mockBaseline(overrides: Partial<{ resources: ResourceSummary[] }> = {}) {
  server.use(
    http.get("/api/resources", () => HttpResponse.json(overrides.resources ?? [careerBankSummary])),
    http.get("/api/resources/settings", () => HttpResponse.json({ write_mode: "prompt" })),
    http.get("/api/resources/pending", () => HttpResponse.json([])),
    http.get("/api/resources/career-bank", () => HttpResponse.json(careerBankDoc)),
  );
}

// ---------- groupResources ----------

test("groupResources buckets career names, then user/agent/other by source", () => {
  const groups = groupResources([
    careerBankSummary, careerProfileSummary, userNoteSummary, agentDraftSummary, seedFaqSummary,
  ]);
  const byKey = Object.fromEntries(groups.map((g) => [g.key, g.items.map((i) => i.name)]));

  expect(byKey.career).toEqual(["career-bank", "career-profile"]);
  expect(byKey.user).toEqual(["notes"]);
  expect(byKey.agent).toEqual(["agent-draft"]);
  expect(byKey.other).toEqual(["faq"]);
});

// ---------- write mode ----------

test("write mode control shows the current mode and PUTs on change", async () => {
  mockBaseline();
  let putBody: unknown = null;
  server.use(
    http.put("/api/resources/settings", async ({ request }) => {
      putBody = await request.json();
      return HttpResponse.json({ write_mode: "full" });
    }),
  );

  renderWithProviders(<ResourcesPage />, { route: "/resources", path: "/resources" });

  const promptRadio = await screen.findByRole("radio", { name: /prompt/i });
  expect(promptRadio).toHaveAttribute("aria-checked", "true");

  const user = userEvent.setup();
  await user.click(screen.getByRole("radio", { name: /full/i }));

  await waitFor(() => expect(screen.getByRole("radio", { name: /full/i })).toHaveAttribute("aria-checked", "true"));
  await waitFor(() => expect(putBody).toEqual({ write_mode: "full" }));
});

test("write mode rolls back and toasts on a failed PUT", async () => {
  mockBaseline();
  server.use(http.put("/api/resources/settings", () => new HttpResponse(null, { status: 500 })));
  const toastSpy = vi.spyOn(toast, "error");

  renderWithProviders(<ResourcesPage />, { route: "/resources", path: "/resources" });
  await screen.findByRole("radio", { name: /prompt/i });

  const user = userEvent.setup();
  await user.click(screen.getByRole("radio", { name: /full/i }));

  await waitFor(() => expect(screen.getByRole("radio", { name: /prompt/i })).toHaveAttribute("aria-checked", "true"));
  expect(toastSpy).toHaveBeenCalled();
});

// ---------- search filter ----------

test("search narrows the resource list by name substring", async () => {
  mockBaseline({ resources: [careerBankSummary, userNoteSummary] });
  renderWithProviders(<ResourcesPage />, { route: "/resources", path: "/resources" });

  await screen.findByText("career-bank");
  expect(screen.getByText("notes")).toBeInTheDocument();

  const user = userEvent.setup();
  await user.type(screen.getByRole("searchbox", { name: /search resources/i }), "career");

  expect(screen.getByText("career-bank")).toBeInTheDocument();
  expect(screen.queryByText("notes")).not.toBeInTheDocument();
});

// ---------- empty resources onboarding ----------

test("empty resources state opens a blank generic resource modal", async () => {
  mockBaseline({ resources: [] });

  renderWithProviders(<ResourcesPage />, { route: "/resources", path: "/resources" });

  expect(await screen.findByText("no resources yet")).toBeInTheDocument();
  expect(screen.getByText(/durable reference material/i)).toBeInTheDocument();

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Create resource" }));

  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByPlaceholderText("career-bank")).toHaveValue("");
  expect(within(dialog).getByRole("combobox")).toHaveValue("json");
  expect(within(dialog).getByRole("button", { name: "Create" })).toBeDisabled();
});

// ---------- create modal ----------

test("create modal validates the name and never PUTs on submit", async () => {
  mockBaseline();
  let putCalled = false;
  server.use(http.put("/api/resources/:name", () => {
    putCalled = true;
    return HttpResponse.json(careerBankDoc);
  }));

  renderWithProviders(<ResourcesPage />, { route: "/resources", path: "/resources" });
  await screen.findByText("career-bank");

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "New resource" }));

  const dialog = await screen.findByRole("dialog");
  const createBtn = within(dialog).getByRole("button", { name: "Create" });
  expect(createBtn).toBeDisabled();

  const nameInput = within(dialog).getByPlaceholderText("career-bank");
  await user.type(nameInput, "Bad Name!");
  expect(createBtn).toBeDisabled();

  await user.clear(nameInput);
  await user.type(nameInput, "my-new-resource");
  expect(createBtn).not.toBeDisabled();

  await user.click(createBtn);

  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(putCalled).toBe(false);
  // the editor opens for the not-yet-persisted draft
  expect(await screen.findByText("my-new-resource")).toBeInTheDocument();
});

test("create modal: Save on a fresh, untouched draft PUTs the empty draft (first save)", async () => {
  mockBaseline();
  let putBody: unknown = null;
  server.use(
    http.put("/api/resources/my-new-resource", async ({ request }) => {
      putBody = await request.json();
      return HttpResponse.json({ ...careerBankDoc, name: "my-new-resource", ...(putBody as object) });
    }),
    // after save, the editor switches from draft to normal mode and refetches by name
    http.get("/api/resources/my-new-resource", () =>
      HttpResponse.json({ ...careerBankDoc, name: "my-new-resource", kind: "json", description: "", content: "" })),
  );

  renderWithProviders(<ResourcesPage />, { route: "/resources", path: "/resources" });
  await screen.findByText("career-bank");

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "New resource" }));

  const dialog = await screen.findByRole("dialog");
  const nameInput = within(dialog).getByPlaceholderText("career-bank");
  await user.type(nameInput, "my-new-resource");
  await user.click(within(dialog).getByRole("button", { name: "Create" }));

  await screen.findByText("my-new-resource");

  // Save without editing anything: the draft must be saveable on the first
  // save even when content/description are untouched (empty).
  const saveBtn = screen.getByRole("button", { name: "Save" });
  expect(saveBtn).not.toBeDisabled();
  await user.click(saveBtn);

  await waitFor(() => expect(putBody).toEqual({ kind: "json", description: "", content: "" }));
});

// ---------- editor: save, inline error, delete ----------

test("editor: typing marks dirty, save invalidates pending, 400 detail shows inline", async () => {
  mockBaseline();

  const { qc } = renderWithProviders(<ResourcesPage />, { route: "/resources?r=career-bank", path: "/resources" });
  const invalidateSpy = vi.spyOn(qc, "invalidateQueries");

  const content = await screen.findByLabelText("content");

  const user = userEvent.setup();
  await user.click(content);
  await user.type(content, "x");

  server.use(
    http.put("/api/resources/career-bank", () =>
      HttpResponse.json({ detail: "csv row 2 has 3 columns, header has 2" }, { status: 400 })),
  );
  await user.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("csv row 2 has 3 columns");

  server.use(
    http.put("/api/resources/career-bank", async ({ request }) => {
      const body = (await request.json()) as { kind: string; description: string; content: string };
      return HttpResponse.json({ ...careerBankDoc, ...body });
    }),
  );
  await user.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  expect(invalidateSpy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["resources", "pending"] }));
});

test("editor: delete goes through a ConfirmDialog before DELETE fires", async () => {
  mockBaseline();
  let deleteCalled = false;
  server.use(http.delete("/api/resources/career-bank", () => {
    deleteCalled = true;
    return HttpResponse.json({ ok: true });
  }));

  renderWithProviders(<ResourcesPage />, { route: "/resources?r=career-bank", path: "/resources" });
  await screen.findByLabelText("content");

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Delete" }));
  expect(deleteCalled).toBe(false);

  const dialog = await screen.findByRole("alertdialog");
  await user.click(within(dialog).getByRole("button", { name: "Delete" }));

  await waitFor(() => expect(deleteCalled).toBe(true));
  expect(await screen.findByText("select a resource")).toBeInTheDocument();
});

test("editor: deleting an unsaved draft discards locally without ever hitting DELETE", async () => {
  mockBaseline();
  let deleteCalled = false;
  server.use(http.delete("/api/resources/my-new-resource", () => {
    deleteCalled = true;
    return HttpResponse.json({ ok: true });
  }));

  renderWithProviders(<ResourcesPage />, { route: "/resources", path: "/resources" });
  await screen.findByText("career-bank");

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "New resource" }));

  const dialog = await screen.findByRole("dialog");
  const nameInput = within(dialog).getByPlaceholderText("career-bank");
  await user.type(nameInput, "my-new-resource");
  await user.click(within(dialog).getByRole("button", { name: "Create" }));

  await screen.findByText("my-new-resource");

  await user.click(screen.getByRole("button", { name: "Delete" }));
  const confirmDialog = await screen.findByRole("alertdialog");
  await user.click(within(confirmDialog).getByRole("button", { name: "Delete" }));

  expect(await screen.findByText("select a resource")).toBeInTheDocument();
  expect(deleteCalled).toBe(false);
});

// ---------- unsaved-changes guard ----------

function renderResourcesWithNav(route: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      {
        path: "/resources",
        element: (
          <>
            <Link to="/skills">go to skills</Link>
            <ResourcesPage />
          </>
        ),
      },
      { path: "/skills", element: <p>skills page</p> },
    ],
    { initialEntries: [route] },
  );
  return render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
}

test("navigating away while dirty is blocked until confirmed", async () => {
  mockBaseline();
  renderResourcesWithNav("/resources?r=career-bank");

  const content = await screen.findByLabelText("content");
  const user = userEvent.setup();
  await user.click(content);
  await user.type(content, "x");

  await user.click(screen.getByRole("link", { name: "go to skills" }));

  expect(await screen.findByRole("heading", { name: /unsaved changes/i })).toBeInTheDocument();
  expect(screen.queryByText("skills page")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Stay" }));
  expect(screen.queryByRole("heading", { name: /unsaved changes/i })).not.toBeInTheDocument();

  await user.click(screen.getByRole("link", { name: "go to skills" }));
  await screen.findByRole("heading", { name: /unsaved changes/i });
  await user.click(screen.getByRole("button", { name: "Leave without saving" }));

  expect(await screen.findByText("skills page")).toBeInTheDocument();
});

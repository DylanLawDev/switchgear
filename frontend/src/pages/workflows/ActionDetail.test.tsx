import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../../test/msw";
import { toast } from "../../components/Toaster";
import { ACTION_BUTTONS, useWorkflowKind } from "../../api/queries/workflows";
import { ActionField, ActionRecord, ActionStatus, ItemRef } from "../../api/types";
import ActionDetail from "./ActionDetail";

const NAME = "job-hunt";
const KEY = "act-1";
const ITEM: ItemRef = { key: "j1", title: "Foo Corp SWE" };

const FIELDS: ActionField[] = [
  { selector: "#name", label: "full name", value: "Ada Lovelace", source: "career-bank", needs_you: false, kind: "text" },
  { selector: "#cover", label: "cover letter", value: "Dear hiring manager", source: "generated", needs_you: true, kind: "multiline" },
];

function actionRecord(status: ActionStatus, overrides: Partial<ActionRecord> = {}): ActionRecord {
  return {
    status,
    fields: FIELDS,
    notes: "",
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    executed_at: null,
    ...overrides,
  };
}

function mockGetAction(record: ActionRecord, item: ItemRef | null = ITEM) {
  server.use(
    http.get(`/api/workflows/${NAME}/actions/${KEY}`, () => HttpResponse.json({ record, item })),
  );
}

function renderDetail(qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  return { qc, ...render(
    <QueryClientProvider client={qc}>
      <ActionDetail workflowName={NAME} actionKey={KEY} />
    </QueryClientProvider>,
  ) };
}

// A harness that also keeps an active subscriber on the actions-list query, so that
// invalidateQueries actually triggers a background refetch we can observe.
function ListHarness() {
  const { data = [] } = useWorkflowKind(NAME, "actions");
  return (
    <div>
      <span data-testid="list-count">{data.length}</span>
      <ActionDetail workflowName={NAME} actionKey={KEY} />
    </div>
  );
}

function renderWithList() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ListHarness />
    </QueryClientProvider>,
  );
}

const STATUSES: ActionStatus[] = ["draft", "approved", "failed", "possibly_executed", "executed", "rejected"];

describe("ACTION_BUTTONS gating matrix — every status × every button", () => {
  test.each(STATUSES)("status=%s: buttons render enabled exactly per `when`", async (status) => {
    mockGetAction(actionRecord(status));
    renderDetail();

    await screen.findByRole("heading", { name: ITEM.title! });
    for (const btn of ACTION_BUTTONS) {
      const button = screen.getByRole("button", { name: btn.label });
      if ((btn.when as readonly string[]).includes(status)) {
        expect(button).toBeEnabled();
      } else {
        expect(button).toBeDisabled();
      }
    }
  });
});

test("field inputs and needs-you checkboxes are editable while draft, disabled otherwise", async () => {
  mockGetAction(actionRecord("draft"));
  renderDetail();

  const nameInput = await screen.findByLabelText(/full name \(/i);
  const coverTextarea = screen.getByLabelText(/cover letter \(/i);
  expect(coverTextarea.tagName).toBe("TEXTAREA");
  expect(coverTextarea).toHaveAttribute("rows", "10");
  expect(nameInput).toBeEnabled();
  expect(coverTextarea).toBeEnabled();
  expect(screen.getByRole("checkbox", { name: "cover letter needs you" })).toBeEnabled();
});

test("field inputs and needs-you checkboxes are disabled once approved", async () => {
  mockGetAction(actionRecord("approved"));
  renderDetail();

  const nameInput = await screen.findByLabelText(/full name \(/i);
  expect(nameInput).toBeDisabled();
  expect(screen.getByLabelText(/cover letter \(/i)).toBeDisabled();
  const checkboxes = screen.getAllByRole("checkbox");
  for (const cb of checkboxes) expect(cb).toBeDisabled();
});

test("Save fields collects {selector, value, needs_you} for every row and POSTs to /fields", async () => {
  mockGetAction(actionRecord("draft"));
  let captured: unknown;
  server.use(
    http.post(`/api/workflows/${NAME}/actions/${KEY}/fields`, async ({ request }) => {
      captured = await request.json();
      return HttpResponse.json(actionRecord("draft"));
    }),
  );
  const user = userEvent.setup();
  renderDetail();

  const nameInput = await screen.findByLabelText(/full name \(/i);
  await user.clear(nameInput);
  await user.type(nameInput, "Grace Hopper");
  await user.click(screen.getByRole("checkbox", { name: "full name needs you" }));

  await user.click(screen.getByRole("button", { name: "Save fields" }));

  await waitFor(() => expect(captured).toBeDefined());
  expect(captured).toEqual({
    fields: [
      { selector: "#name", value: "Grace Hopper", needs_you: true },
      { selector: "#cover", value: "Dear hiring manager", needs_you: true },
    ],
  });
});

test("Reject requires a comment: confirm disabled while blank, POSTs {comment} once filled", async () => {
  mockGetAction(actionRecord("approved"));
  let captured: unknown;
  server.use(
    http.post(`/api/workflows/${NAME}/actions/${KEY}/reject`, async ({ request }) => {
      captured = await request.json();
      return HttpResponse.json(actionRecord("rejected", { rejected_comment: "not a fit" }));
    }),
  );
  const user = userEvent.setup();
  renderDetail();

  await user.click(await screen.findByRole("button", { name: "Reject" }));
  const dialog = await screen.findByRole("alertdialog");
  const dialogConfirm = within(dialog).getByRole("button", { name: "Reject" });
  expect(dialogConfirm).toBeDisabled();

  const textarea = within(dialog).getByLabelText(/why reject/i);
  await user.type(textarea, "not a fit");
  expect(dialogConfirm).toBeEnabled();

  await user.click(dialogConfirm);
  await waitFor(() => expect(captured).toEqual({ comment: "not a fit" }));
});

test("Execute shows a ConfirmDialog first; POST fires only after confirming", async () => {
  mockGetAction(actionRecord("approved"));
  let calls = 0;
  server.use(
    http.post(`/api/workflows/${NAME}/actions/${KEY}/execute`, () => {
      calls += 1;
      return HttpResponse.json(actionRecord("executing"));
    }),
  );
  const user = userEvent.setup();
  renderDetail();

  await user.click(await screen.findByRole("button", { name: "Execute" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText("Execute?")).toBeInTheDocument();
  expect(calls).toBe(0);

  await user.click(within(dialog).getByRole("button", { name: "Execute" }));
  await waitFor(() => expect(calls).toBe(1));
});

test("Mark executed shows a ConfirmDialog first; POST body {outcome:'executed'} fires only after confirming", async () => {
  mockGetAction(actionRecord("possibly_executed"));
  let captured: unknown;
  server.use(
    http.post(`/api/workflows/${NAME}/actions/${KEY}/confirm`, async ({ request }) => {
      captured = await request.json();
      return HttpResponse.json(actionRecord("executed"));
    }),
  );
  const user = userEvent.setup();
  renderDetail();

  await user.click(await screen.findByRole("button", { name: "Mark executed" }));
  expect(await screen.findByText("Mark executed?")).toBeInTheDocument();
  expect(captured).toBeUndefined();

  const dialog = screen.getByRole("alertdialog");
  await user.click(within(dialog).getByRole("button", { name: "Mark executed" }));
  await waitFor(() => expect(captured).toEqual({ outcome: "executed" }));
});

test("Mark failed posts directly (no confirm gate) with body {outcome:'failed'}", async () => {
  mockGetAction(actionRecord("possibly_executed"));
  let captured: unknown;
  server.use(
    http.post(`/api/workflows/${NAME}/actions/${KEY}/confirm`, async ({ request }) => {
      captured = await request.json();
      return HttpResponse.json(actionRecord("failed"));
    }),
  );
  const user = userEvent.setup();
  renderDetail();

  await user.click(await screen.findByRole("button", { name: "Mark failed" }));
  await waitFor(() => expect(captured).toEqual({ outcome: "failed" }));
});

test("Approve posts directly with no body, and the detail pane shows the new status after the round-trip", async () => {
  // Stateful GET so the actions-list invalidate's background refetch of this same detail
  // query (prefix match) agrees with the verb response, exactly like the real backend would
  // — isolates the assertion to "does the UI end up showing approved" rather than a
  // setQueryData-vs-refetch ordering race that a hardcoded-stale GET mock would introduce.
  let status: ActionStatus = "draft";
  server.use(
    http.get(`/api/workflows/${NAME}/actions/${KEY}`, () => HttpResponse.json({ record: actionRecord(status), item: ITEM })),
    http.post(`/api/workflows/${NAME}/actions/${KEY}/approve`, async ({ request }) => {
      const text = await request.text();
      expect(text).toBe("");
      status = "approved";
      return HttpResponse.json(actionRecord("approved"));
    }),
  );
  const user = userEvent.setup();
  renderDetail();

  await screen.findByText("draft");
  await user.click(await screen.findByRole("button", { name: "Approve" }));
  // The verb mutation's setQueryData patch (plus the prefix-invalidated background refetch)
  // must land in the rendered detail pane — direct evidence for the post-verb cache-refresh claim.
  expect(await screen.findByText("approved")).toBeInTheDocument();
});

test("server refusal (200 {error}) surfaces inline, refetches the actions list, and never toasts", async () => {
  mockGetAction(actionRecord("draft", { fields: [] }));
  let listCalls = 0;
  server.use(
    http.get(`/api/workflows/${NAME}/actions`, () => {
      listCalls += 1;
      return HttpResponse.json([{ key: KEY, item: ITEM, status: "draft", needs_you: 0, created_at: 1_700_000_000 }]);
    }),
    http.post(`/api/workflows/${NAME}/actions/${KEY}/approve`, () =>
      HttpResponse.json({ error: "resolve NEEDS-YOU fields before approving" }),
    ),
  );
  const toastSpy = vi.spyOn(toast, "error");
  const user = userEvent.setup();
  renderWithList();

  await waitFor(() => expect(screen.getByTestId("list-count")).toHaveTextContent("1"));
  expect(listCalls).toBe(1);
  await user.click(await screen.findByRole("button", { name: "Approve" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("resolve NEEDS-YOU fields before approving");
  // The actions-list query got invalidated by the same verb mutation and refetched — parity
  // workflow.js refreshAction's unconditional renderActions() on a domain refusal.
  await waitFor(() => expect(listCalls).toBe(2));
  expect(toastSpy).not.toHaveBeenCalled();
});

test("screenshot and confirmation_screenshot render as linked images under /screenshots/", async () => {
  mockGetAction(actionRecord("executed", { screenshot: "before.png", confirmation_screenshot: "after.png" }));
  renderDetail();

  await screen.findByRole("heading", { name: ITEM.title! });
  const beforeImg = screen.getByAltText("before.png") as HTMLImageElement;
  const afterImg = screen.getByAltText("after.png") as HTMLImageElement;
  expect(beforeImg.closest("a")).toHaveAttribute("href", "/screenshots/before.png");
  expect(afterImg.closest("a")).toHaveAttribute("href", "/screenshots/after.png");
});

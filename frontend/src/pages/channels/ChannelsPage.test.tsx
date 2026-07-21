import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../../test/msw";
import { renderWithProviders } from "../../test/utils";
import { ChannelStatus, FlaggedMessage, SendFunction, SuppressionRow, WorkflowDefinition, WorkflowSummary } from "../../api/types";
import ChannelsPage from "../ChannelsPage";

const BASE = "/api/channels/email";

const status: ChannelStatus = {
  name: "email",
  address: "bot@example.com",
  transport: "gmail",
  active: true,
  cursor: "abc123",
  last_poll: 1_700_000_000,
};

const flaggedRow: FlaggedMessage = {
  key: "f1",
  subject: "Urgent <b>sneaky</b> offer",
  sender: "attacker@evil.com",
  received_at: 1_700_000_000,
  triage_reason: "phishing",
};

const fixedFn: SendFunction = {
  name: "reply",
  description: "Reply to sender",
  params: { tone: { type: "enum", values: ["formal", "casual"] } },
  subject_template: "Re: {subject}",
  body_template: "Hi {name}",
  recipient_rule: { type: "fixed", address: "boss@example.com" },
  gate: "approve",
  rate_limit_per_day: 5,
  enabled: true,
  source: "config",
  created_at: 1_700_000_000,
  updated_at: 1_700_000_000,
};

const suppressionRow: SuppressionRow = { address: "spam@example.com", added_at: 1_700_000_000 };

const channelWorkflowSummary: WorkflowSummary = {
  name: "channel-email",
  description: "Email intake channel",
  status: "active",
  stale: false,
  ui_home: "channels",
};

const digestDefinition: WorkflowDefinition = {
  name: "channel-email",
  description: "",
  body: "",
  items: {
    label: "digest",
    label_plural: "digests",
    collection: "digests",
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
const digestItems = [{ key: "d1", subject: "weekly digest" }];

// Baseline handlers every test needs (each test overrides the pieces it exercises).
function mockBaseline() {
  server.use(
    http.get(BASE, () => HttpResponse.json(status)),
    http.get(`${BASE}/flagged`, () => HttpResponse.json([flaggedRow])),
    http.get(`${BASE}/send-functions`, () => HttpResponse.json([fixedFn])),
    http.get(`${BASE}/suppression`, () => HttpResponse.json([suppressionRow])),
    http.get("/api/workflows", () => HttpResponse.json([])),
  );
}

// ---------- status card + poll now ----------

test("status card renders the parity line and Poll now POSTs then refetches status", async () => {
  let pollCount = 0;
  server.use(
    http.get(BASE, () =>
      HttpResponse.json(pollCount === 0 ? status : { ...status, cursor: "def456" }),
    ),
    http.post(`${BASE}/poll`, () => {
      pollCount += 1;
      return HttpResponse.json({ ok: true });
    }),
    http.get(`${BASE}/flagged`, () => HttpResponse.json([])),
    http.get(`${BASE}/send-functions`, () => HttpResponse.json([])),
    http.get(`${BASE}/suppression`, () => HttpResponse.json([])),
    http.get("/api/workflows", () => HttpResponse.json([])),
  );

  renderWithProviders(<ChannelsPage />);

  expect(await screen.findByText(/bot@example\.com/)).toBeInTheDocument();
  expect(screen.getByText(/· active ·/)).toBeInTheDocument();
  expect(screen.getByText(/cursor abc123/)).toBeInTheDocument();

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Poll now" }));

  await waitFor(() => expect(pollCount).toBe(1));
  await waitFor(() => expect(screen.getByText(/cursor def456/)).toBeInTheDocument());
});

test("inactive console-transport status shows (no address) inactive", async () => {
  server.use(
    http.get(BASE, () =>
      HttpResponse.json({ name: "email", address: null, transport: "console", active: false, cursor: null, last_poll: null }),
    ),
    http.get(`${BASE}/flagged`, () => HttpResponse.json([])),
    http.get(`${BASE}/send-functions`, () => HttpResponse.json([])),
    http.get(`${BASE}/suppression`, () => HttpResponse.json([])),
    http.get("/api/workflows", () => HttpResponse.json([])),
  );

  renderWithProviders(<ChannelsPage />);

  expect(await screen.findByText(/\(no address\)/)).toBeInTheDocument();
  expect(screen.getByText(/· inactive ·/)).toBeInTheDocument();
  expect(screen.getByText(/cursor \(none\)/)).toBeInTheDocument();
  expect(screen.getByText(/last poll never/)).toBeInTheDocument();
});

test("send functions and suppression each show a one-liner + create action when empty", async () => {
  server.use(
    http.get(BASE, () => HttpResponse.json(status)),
    http.get(`${BASE}/flagged`, () => HttpResponse.json([])),
    http.get(`${BASE}/send-functions`, () => HttpResponse.json([])),
    http.get(`${BASE}/suppression`, () => HttpResponse.json([])),
    http.get("/api/workflows", () => HttpResponse.json([])),
  );

  renderWithProviders(<ChannelsPage />);
  const user = userEvent.setup();

  await user.click(await screen.findByText("send functions"));
  expect(await screen.findByText("no send functions yet — add one below")).toBeInTheDocument();
  expect(screen.getByLabelText("fn name")).toBeInTheDocument(); // the create form is right there

  await user.click(screen.getByText("suppression list"));
  expect(await screen.findByText("no suppressed addresses yet — add one below")).toBeInTheDocument();
  expect(screen.getByLabelText("suppress address")).toBeInTheDocument();
});

// ---------- flagged queue ----------

test("flagged queue renders subject/sender/received/reason as literal text and File refiles the row away", async () => {
  let flaggedState = [flaggedRow];
  let refileBody: unknown = null;
  mockBaseline();
  server.use(
    http.get(`${BASE}/flagged`, () => HttpResponse.json(flaggedState)),
    http.post(`${BASE}/messages/f1/refile`, async ({ request }) => {
      refileBody = await request.json();
      flaggedState = [];
      return HttpResponse.json({ ok: true });
    }),
  );

  renderWithProviders(<ChannelsPage />);

  expect(await screen.findByText("Urgent <b>sneaky</b> offer")).toBeInTheDocument();
  expect(document.querySelector("b")).not.toBeInTheDocument(); // no HTML injection
  expect(screen.getByText("attacker@evil.com")).toBeInTheDocument();
  expect(screen.getByText("phishing")).toBeInTheDocument();

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "File" }));

  await waitFor(() => expect(refileBody).toEqual({ route: "file" }));
  await waitFor(() => expect(screen.queryByText("Urgent <b>sneaky</b> offer")).not.toBeInTheDocument());
});

// ---------- send function editor ----------

test("send function list shows parity meta and Edit fills the form field-for-field", async () => {
  mockBaseline();
  renderWithProviders(<ChannelsPage />);

  const summary = await screen.findByText("send functions");
  const user = userEvent.setup();
  await user.click(summary);

  expect(screen.getByText("[fixed · gate approve · 5/day · enabled]")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Edit" }));

  expect(screen.getByLabelText("fn name")).toHaveValue("reply");
  expect(screen.getByLabelText("fn description")).toHaveValue("Reply to sender");
  expect(screen.getByLabelText("fn gate")).toHaveValue("approve");
  expect(screen.getByLabelText("fn rule type")).toHaveValue("fixed");
  expect(screen.getByLabelText("fn addresses")).toHaveValue("boss@example.com");
  expect(screen.getByLabelText("fn rate limit")).toHaveValue("5");
  expect(screen.getByLabelText("fn enabled")).toBeChecked();
  expect(screen.getByLabelText("fn subject")).toHaveValue("Re: {subject}");
  expect(screen.getByLabelText("fn body")).toHaveValue("Hi {name}");
  expect(screen.getByLabelText("fn params")).toHaveValue(JSON.stringify(fixedFn.params, null, 2));
});

test("invalid params JSON surfaces an inline error and fires no request", async () => {
  mockBaseline();
  let saveCalled = false;
  server.use(
    http.put(`${BASE}/send-functions/:name`, () => {
      saveCalled = true;
      return HttpResponse.json(fixedFn);
    }),
  );

  renderWithProviders(<ChannelsPage />);
  const user = userEvent.setup();
  await user.click(await screen.findByText("send functions"));
  await user.click(screen.getByRole("button", { name: "Edit" }));

  const params = screen.getByLabelText("fn params");
  await user.clear(params);
  await user.click(params);
  // userEvent.type() treats "{"/"[" as special-key syntax — paste the literal invalid JSON instead.
  await user.paste("{not valid json");

  await user.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByText("params must be valid JSON")).toBeInTheDocument();
  expect(saveCalled).toBe(false);
});

test("save PUTs the exact readForm shape, splitting the comma address list for an allowlist rule", async () => {
  mockBaseline();
  let putBody: unknown = null;
  server.use(
    http.put(`${BASE}/send-functions/:name`, async ({ request }) => {
      putBody = await request.json();
      return HttpResponse.json(fixedFn);
    }),
  );

  renderWithProviders(<ChannelsPage />);
  const user = userEvent.setup();
  await user.click(await screen.findByText("send functions"));
  await user.click(screen.getByRole("button", { name: "Edit" }));

  await user.selectOptions(screen.getByLabelText("fn rule type"), "allowlist");
  const addresses = screen.getByLabelText("fn addresses");
  await user.clear(addresses);
  await user.type(addresses, "a@x.com, b@x.com ,  c@x.com");

  await user.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(putBody).toEqual({
      name: "reply",
      description: "Reply to sender",
      params: fixedFn.params,
      subject_template: "Re: {subject}",
      body_template: "Hi {name}",
      recipient_rule: { type: "allowlist", addresses: ["a@x.com", "b@x.com", "c@x.com"] },
      gate: "approve",
      rate_limit_per_day: 5,
      enabled: true,
    }),
  );
});

test("a 400 detail from the save endpoint renders inline", async () => {
  mockBaseline();
  server.use(
    http.put(`${BASE}/send-functions/:name`, () => HttpResponse.json({ detail: "name already exists" }, { status: 400 })),
  );

  renderWithProviders(<ChannelsPage />);
  const user = userEvent.setup();
  await user.click(await screen.findByText("send functions"));
  await user.click(screen.getByRole("button", { name: "Edit" }));
  await user.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByText("name already exists")).toBeInTheDocument();
});

// ---------- suppression list ----------

test("suppression list adds (PUT) and removes (DELETE) addresses", async () => {
  let rows = [suppressionRow];
  let putAddress: string | null = null;
  mockBaseline();
  server.use(
    http.get(`${BASE}/suppression`, () => HttpResponse.json(rows)),
    http.put(`${BASE}/suppression/:address`, ({ params }) => {
      putAddress = params.address as string;
      rows = [...rows, { address: putAddress, added_at: 1_700_000_500 }];
      return HttpResponse.json({ ok: true });
    }),
    http.delete(`${BASE}/suppression/:address`, ({ params }) => {
      rows = rows.filter((r) => r.address !== params.address);
      return HttpResponse.json({ ok: true });
    }),
  );

  renderWithProviders(<ChannelsPage />);
  const user = userEvent.setup();
  await user.click(await screen.findByText("suppression list"));

  expect(await screen.findByText("spam@example.com")).toBeInTheDocument();

  await user.type(screen.getByLabelText("suppress address"), "new@example.com");
  await user.click(screen.getByRole("button", { name: "Add" }));

  await waitFor(() => expect(putAddress).toBe("new@example.com"));
  expect(await screen.findByText("new@example.com")).toBeInTheDocument();

  const removeButtons = screen.getAllByRole("button", { name: "Remove" });
  await user.click(removeButtons[0]);

  await waitFor(() => expect(screen.queryByText("spam@example.com")).not.toBeInTheDocument());
});

// ---------- digest desk ----------

test("digest desk renders a heading and one RunsView per ui_home:channels workflow", async () => {
  server.use(
    http.get(BASE, () => HttpResponse.json(status)),
    http.get(`${BASE}/flagged`, () => HttpResponse.json([])),
    http.get(`${BASE}/send-functions`, () => HttpResponse.json([])),
    http.get(`${BASE}/suppression`, () => HttpResponse.json([])),
    http.get("/api/workflows", () => HttpResponse.json([channelWorkflowSummary])),
    http.get("/api/workflows/channel-email", () => HttpResponse.json(digestDefinition)),
    http.get("/api/workflows/channel-email/items", () => HttpResponse.json(digestItems)),
    http.get("/api/workflows/channel-email/actions", () => HttpResponse.json([])),
  );

  renderWithProviders(<ChannelsPage />);

  expect(await screen.findByRole("heading", { name: "digest desk", level: 2 })).toBeInTheDocument();
  expect(await screen.findByRole("cell", { name: "weekly digest" })).toBeInTheDocument();
});

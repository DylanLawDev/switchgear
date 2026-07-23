import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, Link, RouterProvider } from "react-router-dom";
import { server } from "../test/msw";
import { renderWithProviders } from "../test/utils";
import { streamChat } from "../api/sse";
import type { ChatEvent, ChatRequest } from "../api/types";
import ChatPage from "./ChatPage";

vi.mock("../api/sse", () => ({ streamChat: vi.fn() }));

const streamChatMock = vi.mocked(streamChat);

function mockConversations() {
  server.use(
    http.get("/api/conversations", () =>
      HttpResponse.json([
        { _id: "conv1", title: "first chat", updated_at: 100 },
        { _id: "conv2", title: "second chat", updated_at: 90 },
      ]),
    ),
    http.get("/api/conversations/conv1", () =>
      HttpResponse.json([
        { kind: "message", role: "user", content: "existing user msg" },
        { kind: "message", role: "assistant", content: "existing **assistant** reply" },
      ]),
    ),
  );
}

test("renders history, streams a reply incrementally, shows a tool marker, and invalidates on done", async () => {
  mockConversations();
  // A manually-resolved deferred forces the "Hel" delta to land in its own React
  // commit before "lo"/tool_call/done fire, so a regressed implementation that
  // buffers all deltas and renders once at stream-end would fail the mid-stream
  // assertion below (review: guard against synchronous-batching false positive).
  let releaseRemainingEvents: () => void = () => {};
  streamChatMock.mockImplementation(async (_body: ChatRequest, onEvent: (e: ChatEvent) => void) => {
    onEvent({ type: "text", delta: "Hel" });
    await new Promise<void>((resolve) => {
      releaseRemainingEvents = resolve;
    });
    onEvent({ type: "tool_call", name: "search", args: {} });
    onEvent({ type: "text", delta: "lo" });
    onEvent({ type: "done", usage: 5 });
  });

  const { qc } = renderWithProviders(<ChatPage />, { route: "/?c=conv1", path: "/" });
  const invalidateSpy = vi.spyOn(qc, "invalidateQueries");

  expect(await screen.findByText("existing user msg")).toBeInTheDocument();
  expect((await screen.findByText("assistant")).tagName).toBe("STRONG");
  expect(await screen.findByText("first chat")).toBeInTheDocument();
  expect(await screen.findByText("second chat")).toBeInTheDocument();

  const user = userEvent.setup();
  const textbox = screen.getByRole("textbox");
  await user.type(textbox, "new message");
  await user.click(screen.getByRole("button", { name: /send/i }));

  expect(await screen.findByText("new message")).toBeInTheDocument();

  // Mid-stream: only the first delta has landed — asserts incremental rendering,
  // not just the final buffered string.
  expect(await screen.findByText("Hel")).toBeInTheDocument();
  expect(screen.queryByText("Hello")).not.toBeInTheDocument();

  releaseRemainingEvents();

  expect(await screen.findByText("Hello")).toBeInTheDocument();

  const marker = await screen.findByText("→ search");
  expect(marker.closest("details")).not.toHaveAttribute("open");

  await waitFor(() => {
    expect(invalidateSpy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: ["conversations"] }));
  });

  expect(streamChatMock).toHaveBeenCalledWith(
    expect.objectContaining({ conversation_id: "conv1", message: "new message" }),
    expect.any(Function),
    expect.any(AbortSignal),
  );
});

test("composer and send button are disabled while streaming", async () => {
  mockConversations();
  let resolveStream: () => void = () => {};
  streamChatMock.mockImplementation(
    (_body: ChatRequest, onEvent: (e: ChatEvent) => void) =>
      new Promise<void>((resolve) => {
        onEvent({ type: "text", delta: "hi" });
        resolveStream = resolve;
      }),
  );

  renderWithProviders(<ChatPage />, { route: "/?c=conv1", path: "/" });
  const user = userEvent.setup();
  const textbox = await screen.findByRole("textbox");
  await user.type(textbox, "go");
  await user.click(screen.getByRole("button", { name: /send/i }));

  await waitFor(() => expect(screen.getByRole("textbox")).toBeDisabled());
  expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();

  resolveStream();
  await waitFor(() => expect(screen.getByRole("textbox")).not.toBeDisabled());
});

test("restores an in-progress response after returning to chat", async () => {
  server.use(
    http.get("/api/conversations", () => HttpResponse.json([
      { _id: "active", title: "active run", updated_at: 100 },
    ])),
    http.get("/api/conversations/active", () => HttpResponse.json([
      { kind: "message", role: "user", content: "keep going" },
      { kind: "message", role: "assistant", content: "Still **working**" },
      { kind: "status", status: "running" },
    ])),
  );

  renderWithProviders(<ChatPage />, { route: "/?c=active", path: "/" });

  expect((await screen.findByText("working")).tagName).toBe("STRONG");
  expect(screen.getByRole("textbox")).toBeDisabled();
  expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
});

test("restores tool calls with collapsible details and resolves resource approval in chat", async () => {
  server.use(
    http.get("/api/conversations", () => HttpResponse.json([
      { _id: "conv1", title: "resource update", updated_at: 100 },
    ])),
    http.get("/api/conversations/conv1", () => HttpResponse.json([
      { kind: "message", role: "assistant", content: "I prepared the **change**." },
      {
        kind: "tool", call_id: "call-1", name: "resources",
        args: { op: "update", name: "career-bank", content: "new" },
        result: { applied: false, queued: true, id: "pending-1", op: "update", name: "career-bank",
          approval: { kind: "resource_write", id: "pending-1" } },
      },
    ])),
    http.get("/api/approvals/resource_write/pending-1", () => HttpResponse.json({
      kind: "resource_write", id: "pending-1", status: "pending",
      title: "update resource career-bank", before: "old line", after: "new line",
    })),
    http.post("/api/approvals/resource_write/pending-1", () => HttpResponse.json({ ok: true })),
  );

  renderWithProviders(<ChatPage />, { route: "/?c=conv1", path: "/" });

  expect((await screen.findByText("change")).tagName).toBe("STRONG");
  expect(await screen.findByText(/Approval required/)).toBeInTheDocument();
  const summary = screen.getByText(/→ resources/);
  expect(summary.closest("details")).not.toHaveAttribute("open");

  const user = userEvent.setup();
  await user.click(summary);
  expect(screen.getAllByText(/\"career-bank\"/)).toHaveLength(2);
  expect(screen.getByText(/\"queued\": true/)).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Approve" }));
  expect(await screen.findByText("Request approved.")).toBeInTheDocument();
});

test("uses the same approval prompt for skill writes", async () => {
  server.use(
    http.get("/api/conversations", () => HttpResponse.json([
      { _id: "skills", title: "skill draft", updated_at: 100 },
    ])),
    http.get("/api/conversations/skills", () => HttpResponse.json([{
      kind: "tool", call_id: "call-2", name: "write_skill", args: { text: "new skill" },
      result: { queued: true, approval: { kind: "skill_write", id: "skill-1" } },
    }])),
    http.get("/api/approvals/skill_write/skill-1", () => HttpResponse.json({
      kind: "skill_write", id: "skill-1", status: "pending",
      title: "create skill helper", before: null, after: "new skill",
    })),
    http.post("/api/approvals/skill_write/skill-1", () => HttpResponse.json({ ok: true })),
  );

  renderWithProviders(<ChatPage />, { route: "/?c=skills", path: "/" });
  expect(await screen.findByText(/create skill helper/)).toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole("button", { name: "Reject" }));
  expect(await screen.findByText("Request rejected.")).toBeInTheDocument();
});

test("new chat clears the selected conversation and sends with a fresh id", async () => {
  mockConversations();
  server.use(http.get("/api/conversations/:id", ({ params }) => {
    if (params.id === "conv1") return HttpResponse.json([
      { kind: "message", role: "user", content: "existing user msg" },
    ]);
    return HttpResponse.json([]);
  }));
  streamChatMock.mockResolvedValue();

  renderWithProviders(<ChatPage />, { route: "/?c=conv1", path: "/" });
  expect(await screen.findByText("existing user msg")).toBeInTheDocument();

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /new chat/i }));
  await waitFor(() => expect(screen.queryByText("existing user msg")).not.toBeInTheDocument());
  await user.type(screen.getByRole("textbox"), "fresh start");
  await user.click(screen.getByRole("button", { name: /send/i }));

  expect(streamChatMock).toHaveBeenCalledWith(
    expect.objectContaining({ conversation_id: expect.not.stringMatching(/^conv1$/), message: "fresh start" }),
    expect.any(Function),
    expect.any(AbortSignal),
  );
});

function renderChatWithNav(route: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: (
          <>
            <Link to="/?c=conv2">go to conv2</Link>
            <ChatPage />
          </>
        ),
      },
    ],
    { initialEntries: [route] },
  );
  return { qc, ...render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>) };
}

test("switching conversations mid-stream aborts the old stream and drops its stragglers", async () => {
  mockConversations();
  server.use(
    http.get("/api/conversations/conv2", () => HttpResponse.json([])),
  );

  let emitConv1Remainder: (() => void) | undefined;
  let conv1Signal: AbortSignal | undefined;
  streamChatMock.mockImplementation(
    (body: ChatRequest, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) => {
      if (body.conversation_id !== "conv1") return new Promise<void>(() => {}); // never resolves, unused here
      conv1Signal = signal;
      onEvent({ type: "text", delta: "from-conv1-early" });
      return new Promise<void>((resolve, reject) => {
        emitConv1Remainder = () => {
          onEvent({ type: "text", delta: "-from-conv1-STALE" });
          resolve();
        };
        signal?.addEventListener("abort", () => {
          const err = new DOMException("Aborted", "AbortError");
          reject(err);
        });
      });
    },
  );

  renderChatWithNav("/?c=conv1");

  expect(await screen.findByText("first chat")).toBeInTheDocument();

  const user = userEvent.setup();
  const textbox = screen.getByRole("textbox");
  await user.type(textbox, "hello from conv1");
  await user.click(screen.getByRole("button", { name: /send/i }));

  expect(await screen.findByText("from-conv1-early")).toBeInTheDocument();
  expect(conv1Signal?.aborted).toBe(false);

  // Switch to conv2 mid-stream.
  await user.click(screen.getByRole("link", { name: "go to conv2" }));

  await waitFor(() => expect(conv1Signal?.aborted).toBe(true));
  // conv1's transcript items must be gone; the composer for conv2 must be usable.
  expect(screen.queryByText("from-conv1-early")).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("textbox")).not.toBeDisabled());

  // conv1's stream keeps delivering events after the abort — they must be dropped
  // silently: no stale text, and no error bubble from the AbortError rejection.
  emitConv1Remainder?.();

  await waitFor(() => {
    expect(screen.queryByText(/from-conv1-STALE/)).not.toBeInTheDocument();
  });
  expect(screen.queryByText(/Aborted/i)).not.toBeInTheDocument();
});

test("bare visit resumes the most recent conversation", async () => {
  mockConversations();
  renderWithProviders(<ChatPage />, { route: "/", path: "/" });
  // conv1 is newest (updated_at 100) — its history should load without ?c
  await screen.findByText("existing user msg");
});

test("new chat stays fresh even with existing conversations", async () => {
  mockConversations();
  renderWithProviders(<ChatPage />, { route: "/?c=conv1", path: "/" });
  await screen.findByText("existing user msg");
  await userEvent.click(screen.getByRole("button", { name: /new chat/i }));
  await waitFor(() =>
    expect(screen.queryByText("existing user msg")).not.toBeInTheDocument());
});

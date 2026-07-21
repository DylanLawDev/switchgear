import { http, HttpResponse } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../../test/msw";
import { renderWithProviders } from "../../test/utils";
import { absTime } from "../../lib/format";
import Toaster from "../../components/Toaster";
import { Memory } from "../../api/types";
import MemoriesPage from "../MemoriesPage";

function makeMemory(overrides: Partial<Memory> = {}): Memory {
  return {
    key: "m1",
    text: "short text",
    type: "core",
    status: "active",
    importance: 5,
    source: "chat",
    conversation_id: null,
    superseded_by: null,
    embedding_model: null,
    created_at: 1700000000,
    updated_at: 1700000000,
    last_accessed_at: 1700000500,
    access_count: 3,
    ...overrides,
  };
}

test("filter chips issue GET with type+status query params; 'all' omits the param", async () => {
  const urls: string[] = [];
  server.use(
    http.get("/api/memories", ({ request }) => {
      urls.push(new URL(request.url).search);
      return HttpResponse.json([]);
    }),
  );

  renderWithProviders(<MemoriesPage />);
  await waitFor(() => expect(urls).toContain(""));

  const user = userEvent.setup();
  const typeGroup = screen.getByRole("group", { name: "filter by type" });
  const statusGroup = screen.getByRole("group", { name: "filter by status" });
  await user.click(within(typeGroup).getByRole("button", { name: "core" }));
  await user.click(within(statusGroup).getByRole("button", { name: "archived" }));

  await waitFor(() => expect(urls[urls.length - 1]).toBe("?type=core&status=archived"));
});

test("verb visibility follows status: active edit+archive, archived restore, superseded neither, delete always", async () => {
  const active = makeMemory({ key: "a", text: "memory a text", status: "active" });
  const archived = makeMemory({ key: "b", text: "memory b text", status: "archived" });
  const superseded = makeMemory({ key: "c", text: "memory c text", status: "superseded" });
  server.use(http.get("/api/memories", () => HttpResponse.json([active, archived, superseded])));

  renderWithProviders(<MemoriesPage />);

  const cardA = (await screen.findByText("memory a text")).closest("article") as HTMLElement;
  const cardB = screen.getByText("memory b text").closest("article") as HTMLElement;
  const cardC = screen.getByText("memory c text").closest("article") as HTMLElement;

  expect(within(cardA).getByRole("button", { name: "Edit" })).toBeInTheDocument();
  expect(within(cardA).getByRole("button", { name: "Archive" })).toBeInTheDocument();
  expect(within(cardA).queryByRole("button", { name: "Restore" })).not.toBeInTheDocument();

  expect(within(cardB).getByRole("button", { name: "Restore" })).toBeInTheDocument();
  expect(within(cardB).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  expect(within(cardB).queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();

  expect(within(cardC).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  expect(within(cardC).queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
  expect(within(cardC).queryByRole("button", { name: "Restore" })).not.toBeInTheDocument();

  for (const card of [cardA, cardB, cardC]) {
    expect(within(card).getByRole("button", { name: "Delete" })).toBeInTheDocument();
  }
});

test("Edit opens a modal prefilled with text and PUTs {text} on save", async () => {
  const memory = makeMemory({ key: "m1", text: "original text" });
  let putBody: unknown;
  server.use(
    http.get("/api/memories", () => HttpResponse.json([memory])),
    http.put("/api/memories/m1", async ({ request }) => {
      putBody = await request.json();
      return HttpResponse.json({ ...memory, ...(putBody as object) });
    }),
  );

  renderWithProviders(<MemoriesPage />);
  await screen.findByText("original text");

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Edit" }));

  const textbox = await screen.findByRole("textbox");
  expect(textbox).toHaveValue("original text");
  await user.clear(textbox);
  await user.type(textbox, "updated text");
  await user.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(putBody).toEqual({ text: "updated text" }));
});

test("New memory modal POSTs {text, type, importance} with importance clamped 1-10", async () => {
  let postBody: unknown;
  server.use(
    http.get("/api/memories", () => HttpResponse.json([])),
    http.post("/api/memories", async ({ request }) => {
      postBody = await request.json();
      return HttpResponse.json({ ...makeMemory(), ...(postBody as object) });
    }),
  );

  renderWithProviders(<MemoriesPage />);
  await screen.findByText("nothing remembered yet");

  const user = userEvent.setup();
  await user.click(screen.getAllByRole("button", { name: "New memory" })[0]);

  await user.type(screen.getByRole("textbox"), "brand new memory");
  await user.click(screen.getByRole("radio", { name: "core" }));

  const importanceInput = screen.getByRole("spinbutton");
  await user.clear(importanceInput);
  await user.type(importanceInput, "15");

  await user.click(screen.getByRole("button", { name: "Create" }));

  await waitFor(() =>
    expect(postBody).toEqual({ text: "brand new memory", type: "core", importance: 10 }),
  );
});

test("restore refusal from the server surfaces as a toast and the list is refetched", async () => {
  const archived = makeMemory({ key: "b", status: "archived", text: "archived memory" });
  let getCount = 0;
  server.use(
    http.get("/api/memories", () => {
      getCount += 1;
      return HttpResponse.json([archived]);
    }),
    http.post("/api/memories/b/restore", () =>
      HttpResponse.json({ detail: "memory not found" }, { status: 404 }),
    ),
  );

  renderWithProviders(
    <>
      <MemoriesPage />
      <Toaster />
    </>,
  );
  await screen.findByText("archived memory");
  expect(getCount).toBe(1);

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Restore" }));

  expect(await screen.findByText("memory not found")).toBeInTheDocument();
  await waitFor(() => expect(getCount).toBe(2));
});

test("search box filters client-side by text substring", async () => {
  const alpha = makeMemory({ key: "a", text: "remember the alpha launch" });
  const beta = makeMemory({ key: "b", text: "remember beta rollout" });
  server.use(http.get("/api/memories", () => HttpResponse.json([alpha, beta])));

  renderWithProviders(<MemoriesPage />);
  await screen.findByText("remember the alpha launch");

  const user = userEvent.setup();
  await user.type(screen.getByRole("searchbox"), "beta");

  expect(screen.queryByText("remember the alpha launch")).not.toBeInTheDocument();
  expect(screen.getByText("remember beta rollout")).toBeInTheDocument();
});

test("card meta line renders type/status/importance/source/last-accessed; long text truncates with expand-on-click", async () => {
  const longText = "x".repeat(200);
  const memory = makeMemory({
    key: "m1",
    text: longText,
    type: "episodic",
    status: "active",
    importance: 7,
    source: "chat",
    last_accessed_at: 1700000000,
  });
  server.use(http.get("/api/memories", () => HttpResponse.json([memory])));

  renderWithProviders(<MemoriesPage />);

  const truncated = `${"x".repeat(160)}…`;
  expect(await screen.findByText(truncated)).toBeInTheDocument();
  expect(screen.queryByText(longText)).not.toBeInTheDocument();

  const metaText = `[episodic · active · importance 7 · chat · last accessed ${absTime(1700000000)}]`;
  expect(screen.getByText(metaText)).toBeInTheDocument();

  const user = userEvent.setup();
  await user.click(screen.getByText(truncated));
  expect(await screen.findByText(longText)).toBeInTheDocument();
});

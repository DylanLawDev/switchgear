import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { server } from "../test/msw";
import { routes } from "../router";
import styles from "./AppShell.module.css";

// renders AppShell inside a memory router at "/" with all six tabs + wire text
function renderShellAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
}

function seedSkillsAndConversations() {
  server.use(
    http.get("/api/skills", () => HttpResponse.json([
      { name: "a", description: "", status: "active", source: "repo", schedule: null },
      { name: "b", description: "", status: "pending", source: "agent", schedule: null },
    ])),
    http.get("/api/conversations", () => HttpResponse.json([])),
    http.get("/api/conversations/:id", () => HttpResponse.json([])),
    http.get("/api/workflows", () => HttpResponse.json([])),
  );
}

test("renders fixed tabs and wire status", async () => {
  seedSkillsAndConversations();
  renderShellAt("/");
  for (const label of ["Chat", "Skills", "Workflows", "Scheduler", "Agents", "Inbox", "Channels", "Resources", "Memories"]) {
    expect(await screen.findByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
  }
  expect(await screen.findByText("agent on duty · 1 skill")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "settings" })).toHaveAttribute("href", "/settings");
});

test("wordmark keeps an accessible name without hover/focus", async () => {
  seedSkillsAndConversations();
  renderShellAt("/");
  expect(await screen.findByRole("link", { name: /switchgear/ })).toBeInTheDocument();
});

test("renders two-letter rail codes", async () => {
  seedSkillsAndConversations();
  renderShellAt("/");
  await screen.findByRole("link", { name: /Workflows/ });
  for (const code of ["CH", "SK", "WF", "SC", "AG", "IN", "CN", "RS", "ME"]) {
    expect(screen.getByText(code)).toBeInTheDocument();
  }
  expect(screen.getAllByText("|")).toHaveLength(9);
});

test("rail defaults open and its toggle persists the preference", async () => {
  seedSkillsAndConversations();
  const user = userEvent.setup();
  renderShellAt("/");
  const collapseBtn = await screen.findByRole("button", { name: "auto-collapse sidebar" });
  const rail = collapseBtn.closest("aside")!;

  expect(rail.className).toContain(styles.railPinned);
  expect(collapseBtn).toHaveTextContent("«");
  expect(collapseBtn).toHaveAttribute("aria-pressed", "false");

  await user.click(collapseBtn);
  expect(rail.className).not.toContain(styles.railPinned);
  expect(collapseBtn).toHaveTextContent("»");
  expect(collapseBtn).toHaveAttribute("aria-pressed", "true");
  expect(collapseBtn).not.toHaveFocus();
  expect(localStorage.getItem("switchgear-rail")).toBe("auto");

  await user.click(collapseBtn);
  expect(rail.className).toContain(styles.railPinned);
  expect(collapseBtn).toHaveAttribute("aria-pressed", "false");
  expect(localStorage.getItem("switchgear-rail")).toBe("pinned");
});

test("theme toggle flips the document theme", async () => {
  seedSkillsAndConversations();
  const user = userEvent.setup();
  renderShellAt("/");
  const themeBtn = await screen.findByRole("button", { name: "toggle theme" });
  const before = document.documentElement.dataset.theme;
  await user.click(themeBtn);
  expect(document.documentElement.dataset.theme).not.toBe(before);
});

test("unknown path renders NotFound", async () => {
  server.use(
    http.get("/api/skills", () => HttpResponse.json([])),
    http.get("/api/workflows", () => HttpResponse.json([])),
  );
  renderShellAt("/nope");
  expect(await screen.findByText(/page not found/i)).toBeInTheDocument();
});

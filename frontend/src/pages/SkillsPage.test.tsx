import { http, HttpResponse } from "msw";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../test/msw";
import { renderWithProviders } from "../test/utils";
import SkillsPage from "./SkillsPage";

const activeSkill = {
  name: "a",
  description: "Does a thing",
  status: "active",
  source: "repo",
  schedule: null,
};
const pendingSkill = {
  name: "b",
  description: "Needs approval",
  status: "pending",
  source: "repo",
  schedule: null,
};

function mockSkills(skills = [activeSkill, pendingSkill]) {
  server.use(http.get("/api/skills", () => HttpResponse.json(skills)));
}

test("renders guidance cards with status-gated approve button", async () => {
  mockSkills();

  renderWithProviders(<SkillsPage />);

  expect(await screen.findByText("a")).toBeInTheDocument();
  expect(screen.getByText("Does a thing")).toBeInTheDocument();
  expect(screen.getByText("b")).toBeInTheDocument();
  expect(screen.getByText("Needs approval")).toBeInTheDocument();

  expect(screen.getByText(/active/)).toBeInTheDocument();
  expect(screen.getByText(/pending/)).toBeInTheDocument();
  expect(screen.getAllByText(/repo/).length).toBeGreaterThan(0);

  const cardA = screen.getByText("a").closest("article") as HTMLElement;
  const cardB = screen.getByText("b").closest("article") as HTMLElement;
  expect(within(cardA).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  expect(within(cardB).getByRole("button", { name: "Approve" })).toBeInTheDocument();
});

test("clicking Approve POSTs and refetches skills", async () => {
  let skillsState = [activeSkill, pendingSkill];
  server.use(
    http.get("/api/skills", () => HttpResponse.json(skillsState)),
    http.post("/api/skills/b/approve", () => {
      skillsState = skillsState.map((s) => (s.name === "b" ? { ...s, status: "active" } : s));
      return HttpResponse.json({ ok: true });
    }),
  );

  renderWithProviders(<SkillsPage />);
  await screen.findByText("b");

  const cardB = screen.getByText("b").closest("article") as HTMLElement;
  const user = userEvent.setup();
  await user.click(within(cardB).getByRole("button", { name: "Approve" }));

  await waitFor(() => {
    const refreshedCardB = screen.getByText("b").closest("article") as HTMLElement;
    expect(within(refreshedCardB).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });
});

test("Edit guidance opens the skill manifest editor", async () => {
  mockSkills();
  server.use(
    http.get("/api/skills/a", () => HttpResponse.json({ ...activeSkill,
      text: "---\nname: a\ndescription: Does a thing\ntools: []\n---\nGuide.\n",
      body: "Guide.", tools: [] })),
  );

  renderWithProviders(<SkillsPage />);
  await screen.findByText("a");

  const cardA = screen.getByText("a").closest("article") as HTMLElement;
  const user = userEvent.setup();
  await user.click(within(cardA).getByRole("button", { name: "Edit guidance" }));
  expect((await screen.findByRole("textbox", {
    name: "skill manifest",
  }) as HTMLTextAreaElement).value).toContain("Guide.");
});

test("saving guidance PUTs the skill manifest", async () => {
  mockSkills();
  let saved = "";
  server.use(
    http.get("/api/skills/a", () => HttpResponse.json({ ...activeSkill,
      text: "---\nname: a\ndescription: Does a thing\ntools: []\n---\nGuide.\n",
      body: "Guide.", tools: [] })),
    http.put("/api/skills/a", async ({ request }) => {
      saved = ((await request.json()) as { text: string }).text;
      return HttpResponse.json({ ok: true });
    }),
  );

  renderWithProviders(<SkillsPage />);
  await screen.findByText("a");

  const cardA = screen.getByText("a").closest("article") as HTMLElement;
  const user = userEvent.setup();
  await user.click(within(cardA).getByRole("button", { name: "Edit guidance" }));
  const editor = await screen.findByRole("textbox", { name: "skill manifest" });
  await user.type(editor, "Updated");
  await user.click(screen.getByRole("button", { name: "Save skill" }));
  await waitFor(() => expect(saved).toContain("Updated"));
});

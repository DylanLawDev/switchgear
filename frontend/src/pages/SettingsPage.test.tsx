import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../test/msw";
import { renderWithProviders } from "../test/utils";
import SettingsPage from "./SettingsPage";

const settings = {
  owner_email: "owner@example.com",
  model_chat: "chat/model",
  model_bulk: "bulk/model",
  model_writing: "writing/model",
  run_token_budget: 200000,
  max_loop_iterations: 20,
  resource_max_bytes: 800000,
  resource_read_chars: 60000,
  memory_max_chars: 1000,
  memory_core_max_chars: 6000,
  memory_recall_k: 4,
  memory_recall_floor: 0.55,
  memory_supersede_threshold: 0.92,
  memory_recency_half_life_days: 14,
  memory_reflection_min_interval: 600,
  channel_body_max_chars: 20000,
  channel_backfill_max: 200,
  channel_reply_rate_per_day: 20,
};

test("edits and saves user-facing settings and shows account controls", async () => {
  let saved: unknown = null;
  server.use(
    http.get("/api/settings", () => HttpResponse.json(settings)),
    http.put("/api/settings", async ({ request }) => {
      saved = await request.json();
      return HttpResponse.json({ ...settings, ...(saved as object) });
    }),
  );
  renderWithProviders(<SettingsPage />);

  const user = userEvent.setup();
  const chatModel = await screen.findByLabelText("Chat model");
  await user.clear(chatModel);
  await user.type(chatModel, "new/chat-model");
  await user.click(screen.getByRole("button", { name: "Save settings" }));

  await waitFor(() => expect(saved).toMatchObject({ model_chat: "new/chat-model" }));
  expect(saved).not.toHaveProperty("owner_email");
  expect(await screen.findByText("saved")).toBeInTheDocument();
  expect(screen.getByText("owner@example.com")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
});

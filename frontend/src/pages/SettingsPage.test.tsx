import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../test/msw";
import { renderWithProviders } from "../test/utils";
import SettingsPage from "./SettingsPage";

const settings = {
  owner: "dylan",
  gateway_base_url: "https://openrouter.ai/api/v1",
  owner_timezone: "Etc/UTC",
  email_backend: "console",
  smtp_host: "",
  smtp_port: 587,
  smtp_username: "",
  smtp_from: "",
  smtp_starttls: true,
  gateway_api_key_set: false,
  smtp_password_set: false,
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

function renderSettings(overrides: Partial<typeof settings> = {}) {
  server.use(http.get("/api/settings", () =>
    HttpResponse.json({ ...settings, ...overrides })));
  return renderWithProviders(<SettingsPage />);
}

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
  expect(saved).not.toHaveProperty("owner");
  expect(saved).not.toHaveProperty("gateway_api_key");
  expect(await screen.findByText("saved")).toBeInTheDocument();
  expect(screen.getByText("dylan")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
});

test("gateway group shows write-only key placeholder and test button", async () => {
  renderSettings({ gateway_api_key_set: true });
  await screen.findByLabelText("Gateway base URL");
  const key = screen.getByLabelText("Gateway API key");
  expect(key).toHaveValue("");
  expect(key).toHaveAttribute("placeholder", expect.stringMatching(/configured/i));
  expect(screen.getByRole("button", { name: /test connection/i })).toBeInTheDocument();
});

test("test connection reports gateway result inline", async () => {
  server.use(http.post("/api/settings/test-gateway", () =>
    HttpResponse.json({ ok: true, models: 7 })));
  renderSettings({});
  const user = userEvent.setup();
  await screen.findByLabelText("Gateway base URL");
  await user.click(screen.getByRole("button", { name: /test connection/i }));
  await screen.findByText(/connected — 7 models/i);
});

test("smtp fields hidden for console backend and shown for smtp", async () => {
  renderSettings({ email_backend: "console" });
  await screen.findByLabelText("Email backend");
  expect(screen.queryByLabelText("SMTP host")).not.toBeInTheDocument();
  const user = userEvent.setup();
  await user.selectOptions(screen.getByLabelText("Email backend"), "smtp");
  expect(screen.getByLabelText("SMTP host")).toBeInTheDocument();
  expect(screen.getByLabelText("SMTP password")).toBeInTheDocument();
});

test("change password posts current and new", async () => {
  let posted: unknown;
  server.use(http.post("/api/settings/password", async ({ request }) => {
    posted = await request.json();
    return HttpResponse.json({ ok: true });
  }));
  renderSettings({});
  const user = userEvent.setup();
  await screen.findByLabelText("Current password");
  await user.type(screen.getByLabelText("Current password"), "old-pass-1");
  await user.type(screen.getByLabelText("New password"), "new-pass-123");
  await user.type(screen.getByLabelText("Confirm new password"), "new-pass-123");
  await user.click(screen.getByRole("button", { name: /change password/i }));
  await screen.findByText(/password changed/i);
  expect(posted).toEqual({ current_password: "old-pass-1", new_password: "new-pass-123" });
});

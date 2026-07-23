import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../test/msw";
import { renderWithProviders } from "../test/utils";
import SetupPage from "./SetupPage";

const settings = {
  owner_email: "me@example.com",
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
  model_chat: "anthropic/claude-sonnet-4.5",
  model_bulk: "b",
  model_writing: "w",
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

function mockUnclaimed() {
  server.use(http.get("/api/setup/status", () =>
    HttpResponse.json({ claimed: false })));
}

test("claim step submits token, email, and password", async () => {
  mockUnclaimed();
  let claimBody: unknown;
  server.use(
    http.post("/api/setup/claim", async ({ request }) => {
      claimBody = await request.json();
      return HttpResponse.json({ ok: true });
    }),
    http.get("/api/settings", () => HttpResponse.json(settings)),
  );
  renderWithProviders(<SetupPage />, { route: "/setup?token=tok-from-url" });

  const user = userEvent.setup();
  await screen.findByText(/claim this instance/i);
  expect(screen.getByLabelText("Setup token")).toHaveValue("tok-from-url");
  await user.type(screen.getByLabelText("Email"), "me@example.com");
  await user.type(screen.getByLabelText("Password"), "hunter22-long");
  await user.type(screen.getByLabelText("Confirm password"), "hunter22-long");
  await user.click(screen.getByRole("button", { name: /claim/i }));

  await screen.findByText(/model gateway/i);
  expect(claimBody).toMatchObject({
    token: "tok-from-url", owner_email: "me@example.com",
    password: "hunter22-long",
  });
});

test("mismatched passwords block submission", async () => {
  mockUnclaimed();
  renderWithProviders(<SetupPage />, { route: "/setup" });
  const user = userEvent.setup();
  await screen.findByText(/claim this instance/i);
  await user.type(screen.getByLabelText("Setup token"), "t");
  await user.type(screen.getByLabelText("Email"), "me@example.com");
  await user.type(screen.getByLabelText("Password"), "hunter22-long");
  await user.type(screen.getByLabelText("Confirm password"), "different-pass");
  await user.click(screen.getByRole("button", { name: /claim/i }));
  await screen.findByText(/passwords do not match/i);
});

test("gateway step tests connection and finishes", async () => {
  mockUnclaimed();
  server.use(
    http.post("/api/setup/claim", () => HttpResponse.json({ ok: true })),
    http.get("/api/settings", () => HttpResponse.json(settings)),
    http.post("/api/settings/test-gateway", () =>
      HttpResponse.json({ ok: true, models: 42 })),
    http.put("/api/settings", async ({ request }) =>
      HttpResponse.json(await request.json())),
  );
  renderWithProviders(<SetupPage />, { route: "/setup?token=t" });
  const user = userEvent.setup();
  await screen.findByText(/claim this instance/i);
  await user.type(screen.getByLabelText("Email"), "me@example.com");
  await user.type(screen.getByLabelText("Password"), "hunter22-long");
  await user.type(screen.getByLabelText("Confirm password"), "hunter22-long");
  await user.click(screen.getByRole("button", { name: /claim/i }));

  await screen.findByText(/model gateway/i);
  await user.type(await screen.findByLabelText("API key"), "sk-new");
  await user.click(screen.getByRole("button", { name: /test connection/i }));
  await screen.findByText(/connected — 42 models/i);
  await user.click(screen.getByRole("button", { name: /save and finish/i }));
  await screen.findByText(/you're all set/i);
});

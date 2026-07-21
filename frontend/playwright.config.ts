import { defineConfig } from "@playwright/test";

// Port 5173 is occupied by an unrelated project's dev server on this host — use a
// dedicated port for the e2e vite instance instead of reusing/killing it.
const PORT = 5273;

export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/helpers/global-setup.ts",
  use: { baseURL: `http://localhost:${PORT}`, storageState: "test-results/auth.json" },
  webServer: [
    {
      // `rm -rf .state-e2e` runs here (not in global-setup.ts): Playwright starts
      // webServer processes *before* it runs custom globalSetup files, so wiping the state
      // dir from global-setup.ts would run after uvicorn has already loaded any stale
      // .state-e2e/storage.json left over from a prior run. Wiping it as part of the
      // command itself guarantees every boot is genuinely fresh. NOTE: `cwd: ".."` below
      // already resolves this command's working directory to the repo root, so the path
      // here must be `.state-e2e`, NOT `../.state-e2e` (that targets one level ABOVE the
      // repo root — `-f` silently swallows the resulting ENOENT, making the wipe a no-op).
      command: "rm -rf .state-e2e && uv run uvicorn switchgear.main:app --port 8000",
      cwd: "..",
      url: "http://localhost:8000/healthz",
      reuseExistingServer: false,
      env: {
        SWITCHGEAR_OWNER_EMAIL: "owner@example.com",
        SWITCHGEAR_SESSION_SECRET: "dev-secret-change-me",
        SWITCHGEAR_STATE_DIR: ".state-e2e",
        SWITCHGEAR_EMAIL_BACKEND: "console",
        SWITCHGEAR_CHANNEL_BACKEND: "console",
        SWITCHGEAR_SCHEDULER_BACKEND: "local",
        SWITCHGEAR_STORAGE_BACKEND: "memory",
      },
    },
    {
      // Dedicated port (see above) — --strictPort makes a stale server on 5273 fail loudly
      // instead of silently falling through to another port.
      command: `npm run dev -- --port ${PORT} --strictPort`,
      url: `http://localhost:${PORT}`,
      reuseExistingServer: false,
    },
  ],
});

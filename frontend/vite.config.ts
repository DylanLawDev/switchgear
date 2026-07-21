/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const BACKEND = "http://localhost:8000";
const PROXIED = ["/api", "/auth", "/login", "/resumes", "/screenshots", "/healthz", "/static/fonts"];

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === "production" ? "/static/app/" : "/",
  build: {
    outDir: "../src/switchgear/web/static/app",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(PROXIED.map((p) => [p, { target: BACKEND }])),
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "src/test/setup.ts",
    exclude: ["e2e/**", "node_modules/**"],
  },
}));

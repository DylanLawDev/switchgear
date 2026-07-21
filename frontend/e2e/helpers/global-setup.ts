import { mkdirSync, writeFileSync } from "node:fs";
import { signedSessionCookie } from "./session";

// The ../.state-e2e wipe lives in playwright.config.ts's backend webServer `command`, not
// here — see the comment there. This just prepares the signed-cookie storageState the
// backend's uvicorn process (already up by the time this runs) will accept.
export default function globalSetup(): void {
  mkdirSync("test-results", { recursive: true });
  writeFileSync("test-results/auth.json", JSON.stringify({
    cookies: [{
      name: "session", value: signedSessionCookie(), domain: "localhost", path: "/",
      expires: -1, httpOnly: true, secure: false, sameSite: "Lax",
    }],
    origins: [],
  }));
}

import { execFileSync } from "node:child_process";

// Verified against src/switchgear/auth.py + src/switchgear/config.py: sign_session(settings, email)
// and Settings(owner_email=..., session_secret=...) match this call shape as written.
export function signedSessionCookie(): string {
  return execFileSync("uv", ["run", "python", "-c", `
from switchgear.auth import sign_session
from switchgear.config import Settings
print(sign_session(Settings(owner_email='owner@example.com',
                            session_secret='dev-secret-change-me'), 'owner@example.com'))
`.trim()], { cwd: "..", encoding: "utf8" }).trim();
}

# Unified setup and runtime gateway configuration

Date: 2026-07-23
Status: approved

## Goal

Make Switchgear deployable the same way everywhere — local Docker, EC2, Cloud
Run — with near-zero required environment configuration. A thin setup script
handles local bootstrap; a browser first-run wizard claims the instance and
configures the model gateway; the Settings page manages gateway, email, timezone,
and password afterwards. Environment variables keep working and act as the
fallback layer.

## Non-goals

- Multi-user support (still single-owner).
- Encrypting secrets at rest inside the database (documented trade-off).
- A `switchgear setup` CLI (future work; it would call the same HTTP APIs).
- Provisioning cloud infrastructure (volumes, Firestore, TLS) — documented, not
  automated.

## Architecture

Extends the existing storage-backed settings-override pattern
(`app-settings` collection, `load_settings_overrides`, live `setattr` on the
shared `Settings` object — which `Gateway` already reads per request).

### Configuration precedence

For every runtime-configurable field: **database value → environment variable →
default**. The database layer is written only by the setup wizard and Settings
UI. Env-only deployments keep working unchanged.

Storage documents in the `app-settings` collection:

| Key | Contents | Returned by API |
|---|---|---|
| `user` (existing) | non-secret preferences; **adds** `gateway_base_url`, `owner_timezone`, `email_backend`, `smtp_host`, `smtp_port`, `smtp_username`, `smtp_from`, `smtp_starttls` | yes, in full |
| `secure` (new) | `gateway_api_key`, `smtp_password`, `local_password_hash`, `owner_email`, `session_secret` (auto-generated only) | never; presence booleans only |
| `setup-token` (new) | one-time claim token; deleted after claim | never |

`load_settings_overrides` applies `user` then `secure`; empty values in
`secure` are skipped (env value stays effective).

### Boot states

- **Claimed**: an effective `local_password_hash` exists (env or DB). Normal
  operation; `/setup` redirects to `/`.
- **Unclaimed**: no effective password hash. `create_app(validate_settings=True)`
  no longer raises for missing `local_password_hash`/`owner_email`; instead the
  app enters setup mode after `load_settings_overrides` runs in lifespan:
  - Setup token resolution order: `SWITCHGEAR_SETUP_TOKEN` env (escape hatch,
    for Cloud Run/EC2 deploys) → persisted `app-settings/setup-token` →
    generate `secrets.token_urlsafe(24)`, persist, and log one line:
    `SETUP required — visit {public_base_url}/setup  token: {token}`
  - Only `/healthz`, `/version`, `/login` (redirects to `/setup`), `/setup`,
    `/api/setup/status`, `/api/setup/claim`, and static assets are useful;
    everything else keeps its normal auth behavior (401 → login → setup).

### Session secret auto-generation

If `session_secret` is the dev default at startup, generate 32 random bytes
(hex), persist to `app-settings/secure`, and use it from then on. Restarts
reuse the persisted value. On storage without persistence this means sessions
reset per restart — documented; setting the env var is the stable path. The
existing "public URL + dev secret" hard fail remains as a safety net if
storage writes fail.

Ordering note: the SQLite storage file lives under `state_dir` and requires no
settings that the wizard configures, so storage is always available before
setup mode begins.

## API surface

New/changed endpoints (all JSON):

- `GET /api/setup/status` (public): `{"claimed": bool}`. Used by the script
  and the wizard; no other data.
- `POST /api/setup/claim` (public, token-gated):
  `{token, password, nickname, owner_timezone?}` →
  validates token with `hmac.compare_digest` (403 + ~0.5 s sleep on failure),
  requires password length ≥ 8, hashes with the existing scrypt helper
  (moved from `cli.py` to `auth.py`; CLI imports from there), writes
  `secure` doc, deletes `setup-token`, sets the session cookie, returns
  `{"ok": true}`. 409 if already claimed.
- `GET /api/settings` (owner): existing fields plus `gateway_base_url`,
  `owner_timezone`, `email_backend`, `smtp_host`, `smtp_port`,
  `smtp_username`, `smtp_from`, `smtp_starttls`, and presence booleans
  `gateway_api_key_set`, `smtp_password_set`. Secret values are never echoed.
- `PUT /api/settings` (owner): accepts the extended non-secret set plus
  optional write-only `gateway_api_key` and `smtp_password` (absent or empty
  string = keep current). Non-secrets → `user` doc; secrets → `secure` doc.
  Both applied to the live settings object immediately.
- `POST /api/settings/test-gateway` (owner):
  `{gateway_base_url?, gateway_api_key?}` — missing fields fall back to
  effective values (so "test what I typed" and "test what's saved" both work;
  an empty `gateway_api_key` string also falls back so the saved key can be
  tested without re-entering it). Performs `GET {base_url}/models` with the
  bearer key, 10 s timeout. Returns `{"ok": true, "models": <count>}` or
  `{"ok": false, "detail": str}` with HTTP 200 (failure is data, not an
  error). Known limitation: a gateway without `/models` reports failure —
  documented in the UI copy.
- `POST /api/settings/password` (owner): `{current_password, new_password}` —
  verifies current against the effective hash, writes new hash to `secure`.
  Sessions stay valid (cookie is signed by session secret, not the hash).

`UserSettings` model grows the non-secret fields with validation
(`email_backend: Literal["console","smtp"]`, `smtp_port: 1–65535`,
`owner_timezone` validated against `zoneinfo.available_timezones()`,
URL fields `min_length=1` http(s)).

## Email backend switching

`get_email_sender` returns a `DynamicEmailSender` that reads
`settings.email_backend` at send time and delegates to a `ConsoleEmailSender`
or `SMTPEmailSender` instance (both constructed up front; SMTP already reads
settings per send). Console output remains the default.

## Frontend

- **`/setup` — SetupPage**, routed outside `AppShell` (no nav chrome).
  Three steps, single card layout:
  1. **Claim**: token (pre-filled from `?token=` query param), nickname
     (local tenants need no email; `SWITCHGEAR_OWNER_EMAIL` remains the
     env-configured option for email features), password + confirm. Submits claim; on success proceeds (session cookie now
     set).
  2. **Gateway**: base URL (default from settings), API key, chat model;
     "Test connection" button calling test-gateway; Save via
     `PUT /api/settings`. Skippable ("configure later in Settings").
  3. **Done**: link to `/`.
  If `GET /api/setup/status` says claimed, redirect to `/`.
- **SettingsPage** gains groups:
  - *gateway*: base URL, API key (password input, placeholder "configured ✓ —
    enter to replace" when `gateway_api_key_set`), test-connection button with
    inline result.
  - *email*: backend toggle (console/smtp), SMTP host/port/username/from/
    starttls, SMTP password (write-only like the API key). SMTP fields hidden
    when backend is console.
  - *account* (extends existing): owner timezone select, change-password form
    (current + new + confirm), existing logout.
- Backend serves `GET /setup` returning the SPA without auth (redirect to `/`
  when claimed).

## Setup script

`scripts/setup.sh` (bash, idempotent, Docker Compose required):

1. `cp .env.example .env` if missing.
2. If `SWITCHGEAR_SESSION_SECRET` is empty in `.env`, fill with
   `openssl rand -hex 32` (fallback: `python3 -c "import secrets; ..."`).
3. `docker compose up -d --build`.
4. Poll `http://127.0.0.1:${SWITCHGEAR_PORT:-8080}/healthz` (120 s timeout).
5. `GET /api/setup/status`; if unclaimed, extract the token from
   `docker compose logs switchgear` and print:
   `Open http://127.0.0.1:8080/setup?token=…` — else print "already
   configured, open http://127.0.0.1:8080".

`.env.example` shrinks to session secret + optional overrides;
`SWITCHGEAR_LOCAL_PASSWORD_HASH` and the gateway block become optional
documented overrides. The `hash-password` CLI command remains for env-based
deployments.

## Cloud deployment story (docs)

- Persistent storage is a prerequisite (volume mount for SQLite, or Firestore
  backend). Without it, claims and tokens reset on cold start.
- Read the token: `docker logs switchgear` (EC2) /
  `gcloud run services logs read …` (Cloud Run) — or preset
  `SWITCHGEAR_SETUP_TOKEN` at deploy time and skip logs entirely.
- Set `SWITCHGEAR_SESSION_SECRET` env for stable sessions; set
  `SWITCHGEAR_PUBLIC_BASE_URL` and keep `SWITCHGEAR_COOKIE_SECURE=true`
  behind TLS.

## Security notes (added to SECURITY.md)

- Secrets set via UI rest unencrypted in the database; the database file has
  the same trust level as `/data` generally. Protect the volume.
- Setup token: single-use, deleted on claim, constant-time compared, never
  served by any endpoint, present in logs — rotate by deleting the
  `app-settings/setup-token` document and restarting if leaked pre-claim.
- Claim endpoint is intentionally exempt from session CSRF (no session exists);
  the token is the credential.

## Testing

- **Backend** (pytest, existing fakes): unclaimed boot generates + persists
  token and honors `SWITCHGEAR_SETUP_TOKEN`; claim happy path sets cookie and
  deletes token; wrong token 403; second claim 409; status endpoint; settings
  precedence DB-over-env after restart; secrets write-only round-trip (PUT with
  and without key; GET never echoes); test-gateway success/auth-failure/timeout
  via mocked transport; password change (wrong current 403, effective-hash
  precedence); session-secret auto-generation persists across app recreation;
  DynamicEmailSender switches per send.
- **Frontend** (vitest + msw): SetupPage step flow, token prefill, claim error
  display, test-connection result rendering; SettingsPage new groups,
  write-only placeholder behavior, SMTP fields visibility toggle.
- **Docs/script**: smoke-check `scripts/setup.sh` with `bash -n` in CI lint;
  manual verification of full Compose flow before PR.

## Affected files (indicative)

Backend: `config.py`, `auth.py`, `cli.py`, `web/app.py`,
`web/settings_routes.py`, new `web/setup_routes.py`, `email/__init__.py`,
`email/sender.py`. Frontend: `router.tsx`, new `pages/SetupPage.tsx`,
`pages/SettingsPage.tsx`, `api/types.ts`, `api/queries/settings.ts`, new
`api/queries/setup.ts`. Scripts/docs: `scripts/setup.sh`, `.env.example`,
`README.md`, `docs/configuration.md`, `docs/self-hosting.md`, `SECURITY.md`,
`compose.yaml` (no changes expected beyond docs references).

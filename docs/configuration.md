# Configuration

Settings use the `SWITCHGEAR_` prefix and may be placed in `.env`. The selected adapters
are validated on service startup.

## Precedence

Values set through the setup wizard or Settings UI are stored in the database
and take precedence over environment variables, which take precedence over
defaults. Secrets saved through the UI (gateway API key, SMTP password,
password hash) are write-only: the API reports only whether they are set.

| Group | Setting | Default | Notes |
|---|---|---|---|
| Core | `SWITCHGEAR_STATE_DIR` | `.state` | Container images set `/data`. |
| Setup | `SWITCHGEAR_SETUP_TOKEN` | generated | Presets the one-time claim token; otherwise it is generated and logged on first boot (`SETUP required — … token: …`). |
| Models | `SWITCHGEAR_GATEWAY_BASE_URL` | OpenRouter-compatible URL | Any OpenAI-compatible gateway. |
| Models | `SWITCHGEAR_GATEWAY_API_KEY` | empty | Required by the configured gateway. |
| Storage | `SWITCHGEAR_STORAGE_BACKEND` | `sqlite` | `sqlite`, `memory`, or optional `firestore`. |
| Auth | `SWITCHGEAR_LOCAL_PASSWORD_HASH` | empty | Generate with `switchgear hash-password`. |
| Auth | `SWITCHGEAR_SESSION_SECRET` | development value | Use at least 32 random bytes in production. |
| Auth | `SWITCHGEAR_COOKIE_SECURE` | `true` | Set false only for localhost HTTP. |
| Email | `SWITCHGEAR_EMAIL_BACKEND` | `console` | `console` or `smtp`. |
| SMTP | `SWITCHGEAR_SMTP_HOST`, `SWITCHGEAR_SMTP_FROM` | empty | Required when SMTP is selected. |
| Scheduling | `SWITCHGEAR_SCHEDULER_BACKEND` | `local` | `cloud` uses GCP Scheduler and Tasks. |
| Browser | `SWITCHGEAR_PDF_BACKEND` | `none` | `chromium` requires the browser image/extra. |

Firestore and cloud scheduling require the `gcp` extra and normal provider identity
configuration. Missing optional packages produce an import error only when their
adapter is selected.

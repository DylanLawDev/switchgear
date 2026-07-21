# Switchgear

**The control plane for autonomous work.**

A private, single-owner agent application with chat, workflows, schedules,
resources, memory, approvals, email, and optional browser automation. The default
self-hosted deployment is one container, one SQLite database, and one persistent
volume. Google Cloud is optional.

## Five-minute local start

Requirements: Docker with Compose and an OpenAI-compatible model gateway key.

```sh
cp .env.example .env
openssl rand -hex 32                 # paste into SWITCHGEAR_SESSION_SECRET
docker compose run --rm switchgear switchgear hash-password
# paste the result into SWITCHGEAR_LOCAL_PASSWORD_HASH, then set the gateway key
docker compose up -d
curl --fail http://127.0.0.1:8080/healthz
```

Open <http://127.0.0.1:8080>. Compose binds only to localhost. Data lives in the
`switchgear-data` volume at `/data`; the database is `/data/switchgear.sqlite3` and generated
files remain below `/data`.

This release supports one application process and one replica. Do not expose it
without authentication, and put a TLS reverse proxy in front before binding it to a
public interface. See [self-hosting](docs/self-hosting.md) and
[configuration](docs/configuration.md).

## Images and integrations

The default image is lightweight. Build the browser image with
`docker build --target browser -t switchgear:browser .`; it includes Playwright
and Chromium. Released deployments should use immutable semantic-version tags or
digests, never `main` or `latest`.

The base Python installation has no provider-specific identity or mail packages.
Install `.[gcp]` or `.[browser]` only when selecting those adapters. Console email
is the zero-configuration default; SMTP is the portable production option.

## Development

```sh
UV_CACHE_DIR=/tmp/uv-cache uv sync --all-extras
UV_CACHE_DIR=/tmp/uv-cache uv run pytest
cd frontend && npm ci && npm test && npm run build
```

See [backup and restore](docs/backup-and-restore.md),
[deployment integrations](docs/deployment-integrations.md), and [security](SECURITY.md).

Licensed under the [Apache License 2.0](LICENSE).

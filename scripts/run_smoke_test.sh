#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$(mktemp)"
PROJECT="switchgear-smoke-$RANDOM"
cleanup() {
  docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" down --volumes || true
  rm -f "$ENV_FILE"
}
trap cleanup EXIT

HASH="$(uv run python -c "from switchgear.cli import hash_password; print(hash_password('smoke-password'))")"
cat >"$ENV_FILE" <<EOF
SWITCHGEAR_SESSION_SECRET=smoke-session-secret-with-at-least-32-bytes
SWITCHGEAR_LOCAL_PASSWORD_HASH=$HASH
SWITCHGEAR_OWNER_EMAIL=owner@example.com
SWITCHGEAR_GATEWAY_API_KEY=smoke-not-used
SWITCHGEAR_ENV_FILE=$ENV_FILE
EOF

cd "$ROOT"
docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" up -d --build --wait agent
for _ in $(seq 1 30); do
  curl --fail --silent http://127.0.0.1:8080/healthz && break
  sleep 2
done
curl --fail --silent http://127.0.0.1:8080/healthz >/dev/null
docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" exec -T agent \
  python -c "import asyncio; from switchgear.storage.sqlite import SQLiteStorage; asyncio.run(SQLiteStorage('/data/switchgear.sqlite3').put('smoke','persistent',{'ok':True}))"
docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" up -d --force-recreate --wait agent
docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" exec -T agent \
  python -c "import asyncio; from switchgear.storage.sqlite import SQLiteStorage; assert asyncio.run(SQLiteStorage('/data/switchgear.sqlite3').get('smoke','persistent')) == {'ok': True}"

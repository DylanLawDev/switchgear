#!/usr/bin/env bash
# One-command local setup: env bootstrap, container start, setup-wizard handoff.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${SWITCHGEAR_PORT:-8080}"
BASE="http://127.0.0.1:${PORT}"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "created .env from .env.example"
fi

if ! grep -Eq '^SWITCHGEAR_SESSION_SECRET=.+' .env; then
  if command -v openssl >/dev/null 2>&1; then
    secret="$(openssl rand -hex 32)"
  else
    secret="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  fi
  if grep -q '^SWITCHGEAR_SESSION_SECRET=' .env; then
    sed -i.bak "s|^SWITCHGEAR_SESSION_SECRET=.*|SWITCHGEAR_SESSION_SECRET=${secret}|" .env \
      && rm -f .env.bak
  else
    printf 'SWITCHGEAR_SESSION_SECRET=%s\n' "${secret}" >> .env
  fi
  echo "generated session secret"
fi

docker compose up -d --build

echo -n "waiting for ${BASE}/healthz "
for _ in $(seq 1 60); do
  if curl -fsS "${BASE}/healthz" >/dev/null 2>&1; then
    echo " ok"
    break
  fi
  echo -n "."
  sleep 2
done
curl -fsS "${BASE}/healthz" >/dev/null || {
  echo
  echo "service did not become healthy; check: docker compose logs switchgear"
  exit 1
}

claimed="$(curl -fsS "${BASE}/api/setup/status" | grep -o '"claimed":[a-z]*' | cut -d: -f2)"
if [ "${claimed}" = "true" ]; then
  echo "Already configured — open ${BASE}"
  exit 0
fi

token="$(docker compose logs switchgear 2>&1 | grep 'SETUP required' | tail -1 \
  | sed -n 's/.*token: \([^ ]*\).*/\1/p')"
if [ -n "${token}" ]; then
  echo
  echo "Finish setup in your browser:"
  echo "  ${BASE}/setup?token=${token}"
else
  echo "Setup pending but no token found in logs; run: docker compose logs switchgear | grep 'SETUP required'"
fi

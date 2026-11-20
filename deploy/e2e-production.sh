#!/usr/bin/env bash
# The e2e suite once through the production images and proxy (#178): deploy/deploy.sh starts the
# stack of deploy/compose.yaml under its own project name, with throwaway secrets, settings, a
# self-signed certificate for localhost and a local backup repository (deploy/e2e-common.sh);
# seed_e2e makes the e2e users; Playwright runs against https://localhost:$E2E_HTTPS_PORT. Everything is removed afterwards, the volume included.
#
#   deploy/e2e-production.sh [playwright args]   E2E_HTTPS_PORT (8443), E2E_HTTP_PORT (8080) move it
set -euo pipefail
cd "$(dirname "$0")"
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-cultures-e2e-production}
export HTTPS_PORT=${E2E_HTTPS_PORT:-8443} HTTP_PORT=${E2E_HTTP_PORT:-8080}
export WEB_SUBNET=${E2E_WEB_SUBNET:-10.179.0.0/24} PROXY_ADDRESS=${E2E_PROXY_ADDRESS:-10.179.0.10}
export E2E_PASSWORD=${E2E_PASSWORD:-$(head -c 24 /dev/urandom | base64 | tr -d '/+=\n')}
# shellcheck source=e2e-common.sh
. ./e2e-common.sh
trap 'e2e_cleanup $?' EXIT

./deploy.sh

echo "== e2e users"
# seed_e2e refuses without DEBUG: it runs once with the development settings, against the same
# database as the runtime role, and never in a real deployment.
docker compose -f compose.yaml run --rm -T --no-deps \
  -e DJANGO_SETTINGS_MODULE=config.settings.local -e DJANGO_SECRET_KEY_FILE= -e E2E_PASSWORD \
  backend python manage.py seed_e2e >/dev/null || fail "seed_e2e"

echo "== e2e through https://localhost:$HTTPS_PORT"
headers=$(curl -ksS -D - -o /dev/null "https://localhost:$HTTPS_PORT/")
grep -qi "^content-security-policy: .*'nonce-[0-9a-f]\{32\}'" <<<"$headers" \
  || fail "the SPA came without a nonce in its CSP: $headers"
cd ../frontend
E2E_BASE_URL="https://localhost:$HTTPS_PORT" npx playwright test "$@"

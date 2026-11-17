#!/usr/bin/env bash
# The e2e suite once through the production images and proxy (#178): deploy/deploy.sh starts the
# stack of deploy/compose.yaml under its own project name, with throwaway secrets, settings and a
# self-signed certificate for localhost; seed_e2e makes the e2e users; Playwright runs against
# https://localhost:$E2E_HTTPS_PORT. Everything is removed afterwards, the volume included.
#
#   deploy/e2e-production.sh [playwright args]   E2E_HTTPS_PORT (8443), E2E_HTTP_PORT (8080) move it
set -euo pipefail
cd "$(dirname "$0")"
fail() { echo "FAILED: $1" >&2; exit 1; }

work=$(mktemp -d)
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-cultures-e2e-production}
export HTTPS_PORT=${E2E_HTTPS_PORT:-8443} HTTP_PORT=${E2E_HTTP_PORT:-8080}
export ENV_FILE=$work/env SECRETS_DIR=$work/secrets TLS_DIR=$work/certs
export WEB_SUBNET=${E2E_WEB_SUBNET:-10.179.0.0/24} PROXY_ADDRESS=${E2E_PROXY_ADDRESS:-10.179.0.10}
export DJANGO_ADMIN_PATH=e2e-admin-$RANDOM/
export E2E_PASSWORD=${E2E_PASSWORD:-$(head -c 24 /dev/urandom | base64 | tr -d '/+=\n')}
cleanup() {
  local status=$?
  # The logs go with the stack: print them while it is still there.
  [ "$status" -eq 0 ] || docker compose -f compose.yaml logs --tail 60 backend proxy 2>&1 || true
  docker compose -f compose.yaml down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

cat > "$ENV_FILE" <<ENV
DJANGO_ALLOWED_HOSTS=localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost:$HTTPS_PORT
DJANGO_ADMIN_PATH=$DJANGO_ADMIN_PATH
ENV
mkdir -p "$TLS_DIR"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=localhost \
  -addext subjectAltName=DNS:localhost -keyout "$TLS_DIR/privkey.pem" -out "$TLS_DIR/fullchain.pem" \
  >/dev/null 2>&1 || fail "openssl could not make the test certificate"
# The proxy runs as uid 101: it must read the key.
chmod 644 "$TLS_DIR/privkey.pem"

./deploy.sh secrets >/dev/null
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

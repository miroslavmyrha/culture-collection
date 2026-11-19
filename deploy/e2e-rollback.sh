#!/usr/bin/env bash
# The rollback of deploy/deploy.sh (#179), without the registry: release 0.0.1 is deployed from
# images built here, then 0.0.2, whose proxy never turns healthy. The deploy of 0.0.2 must fail,
# and 0.0.1 must run again, healthy and answering, with the state file still naming it.
# LOCAL_RELEASE skips the signature check, which only local/ images can do. Everything is
# removed afterwards, the volume and the two test tags included.
#
#   deploy/e2e-rollback.sh   E2E_HTTPS_PORT (8543), E2E_HTTP_PORT (8180) move it
set -euo pipefail
cd "$(dirname "$0")"
fail() { echo "FAILED: $1" >&2; exit 1; }
compose() { docker compose -f compose.yaml "$@"; }

work=$(mktemp -d)
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-cultures-e2e-rollback}
export HTTPS_PORT=${E2E_HTTPS_PORT:-8543} HTTP_PORT=${E2E_HTTP_PORT:-8180}
export ENV_FILE=$work/env SECRETS_DIR=$work/secrets TLS_DIR=$work/certs STATE_DIR=$work/state
export WEB_SUBNET=${E2E_WEB_SUBNET:-10.180.0.0/24} PROXY_ADDRESS=${E2E_PROXY_ADDRESS:-10.180.0.10}
export DJANGO_ADMIN_PATH=e2e-admin-$RANDOM/ LOCAL_RELEASE=1
backend=local/culture-collection-backend proxy=local/culture-collection-proxy
cleanup() {
  local status=$?
  [ "$status" -eq 0 ] || compose logs --tail 40 backend proxy 2>&1 || true
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  docker rmi "$backend:0.0.1" "$backend:0.0.2" "$proxy:0.0.1" "$proxy:0.0.2" >/dev/null 2>&1 || true
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
chmod 644 "$TLS_DIR/privkey.pem"
./deploy.sh secrets >/dev/null

echo "== two releases: 0.0.1, and 0.0.2 with a proxy that never turns healthy"
docker build -q --target runtime -t "$backend:0.0.1" ../backend >/dev/null || fail "the backend image"
docker build -q -t "$proxy:0.0.1" ../frontend >/dev/null || fail "the proxy image"
docker tag "$backend:0.0.1" "$backend:0.0.2"
printf 'FROM %s\nHEALTHCHECK --interval=2s --timeout=2s --retries=2 CMD false\n' "$proxy:0.0.1" \
  | docker build -q -t "$proxy:0.0.2" - >/dev/null || fail "the broken proxy image"

echo "== deploy 0.0.1"
./deploy.sh 0.0.1 || fail "release 0.0.1 did not deploy"
grep -qx VERSION=0.0.1 "$STATE_DIR/current" || fail "the state does not name 0.0.1 after its deploy"

echo "== deploy 0.0.2, which must fail and roll back"
if ./deploy.sh 0.0.2; then
  fail "release 0.0.2 deployed with a proxy that is never healthy"
fi

running=$(docker inspect -f '{{.Config.Image}}' "$(compose ps -q proxy)")
[ "$running" = "$proxy:0.0.1" ] || fail "after the rollback the proxy runs $running, not $proxy:0.0.1"
health=$(docker inspect -f '{{.State.Health.Status}}' "$(compose ps -q proxy)")
[ "$health" = healthy ] || fail "after the rollback the proxy is $health"
code=$(curl -ks -o /dev/null -w '%{http_code}' "https://localhost:$HTTPS_PORT/api/v1/auth/csrf/")
[ "$code" = 204 ] || fail "after the rollback the API answers $code through the proxy"
grep -qx VERSION=0.0.1 "$STATE_DIR/current" || fail "the state names $(cat "$STATE_DIR/current")"
[ ! -e "$STATE_DIR/previous" ] || fail "a failed release moved the state"
echo "rolled back: 0.0.1 runs, healthy, and the state names it"

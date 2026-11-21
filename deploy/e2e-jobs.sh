#!/usr/bin/env bash
# The scheduled jobs through the production stack (#180): deploy/deploy.sh starts it (shared setup
# in deploy/e2e-common.sh) with the ping URL pointing at a Healthchecks stand-in (e2e-pings.py).
# Then:
#   1. supercronic itself runs the heartbeat (a test crontab, every ten seconds), and it pings
#      start and success: the API is ready and the proxy serves the app;
#   2. every line of backend/crontab, as written there, runs once in the scheduler: each pings
#      start, then success, except the anchor job, which fails with 1 while no timestamp
#      authority is configured, and says so in its ping;
#   3. a broken job pings its exit code.
# Everything is removed afterwards, the volume included.
#
#   deploy/e2e-jobs.sh      E2E_HTTPS_PORT (8463), E2E_HTTP_PORT (8083) move it
set -euo pipefail
cd "$(dirname "$0")"
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-cultures-e2e-jobs}
export HTTPS_PORT=${E2E_HTTPS_PORT:-8463} HTTP_PORT=${E2E_HTTP_PORT:-8083}
export WEB_SUBNET=${E2E_WEB_SUBNET:-10.182.0.0/24} PROXY_ADDRESS=${E2E_PROXY_ADDRESS:-10.182.0.10}
export E2E_PASSWORD=${E2E_PASSWORD:-$(head -c 24 /dev/urandom | base64 | tr -d '/+=\n')}
# shellcheck source=e2e-common.sh
. ./e2e-common.sh
trap 'e2e_cleanup $?' EXIT
jobs_compose() { docker compose -f compose.yaml -f e2e-jobs.yaml "$@"; }

KEY=e2e-ping-key
echo "http://pings:8000/ping/$KEY" > "$SECRETS_DIR/healthchecks_ping_url"
export E2E_CRONTAB=$work/crontab
cat > "$E2E_CRONTAB" <<CRON
*/10 * * * * * * python tools/run_job.py heartbeat --timeout 60 -- python tools/heartbeat.py --insecure-internal-tls http://backend:8000/readyz https://proxy:8443/
CRON

./deploy.sh

echo "== e2e data"
docker compose -f compose.yaml run --rm -T --no-deps \
  -e DJANGO_SETTINGS_MODULE=config.settings.local -e DJANGO_SECRET_KEY_FILE= -e E2E_PASSWORD \
  backend python manage.py seed_e2e >/dev/null || fail "seed_e2e"

echo "== the crontab parses"
jobs_compose exec -T scheduler supercronic -test /app/crontab >/dev/null || fail "backend/crontab does not parse"

echo "== the stand-in and the test crontab"
SCHEDULER_CRONTAB=/e2e/crontab jobs_compose up -d --no-build --wait pings scheduler >/dev/null \
  || fail "the stand-in or the scheduler did not start"
pings() { jobs_compose exec -T pings cat /tmp/pings.log; }
# pinged <path> [<text in the body>]: a ping to that path, with that text when given.
pinged() { pings | awk -F'\t' -v p="/ping/$KEY/$1" -v t="${2:-}" '$1 == p && index($2, t) { found = 1 } END { exit !found }'; }

echo "== supercronic runs the heartbeat"
for _ in $(seq 30); do pinged heartbeat ": ok" && break; sleep 2; done
pinged heartbeat/start || fail "no heartbeat start ping from supercronic: $(pings)"
pinged heartbeat "http://backend:8000/readyz: ok" || fail "no heartbeat success ping: $(pings)"

echo "== every job of backend/crontab once"
jobs_compose exec -T scheduler sh -c \
  "grep -Ev '^(#|$)' /app/crontab | cut -d' ' -f6- | while read -r job; do sh -c \"\$job\" </dev/null || true; done" \
  >/dev/null 2>&1
for check in prune-login-failures clearsessions audit-reconcile; do
  pinged "$check/start" || fail "$check: no start ping: $(pings)"
  pinged "$check" || fail "$check: no success ping: $(pings)"
done
pinged audit-chain-anchor/start || fail "audit-chain-anchor: no start ping"
pinged audit-chain-anchor/1 "unanchored" \
  || fail "audit-chain-anchor: no failure ping naming the unanchored chains: $(pings)"
pinged audit-chain-anchor && fail "audit-chain-anchor pinged success without an authority"

echo "== a broken job pings its exit code"
set +e
jobs_compose exec -T scheduler python tools/run_job.py broken -- python manage.py no_such_command >/dev/null 2>&1
code=$?
set -e
[ "$code" -ne 0 ] || fail "the broken job ended with 0"
pinged "broken/$code" "Unknown command" || fail "the broken job did not ping /$code with its output: $(pings)"
pinged broken && fail "the broken job pinged success"

echo "jobs: heartbeat from supercronic, 4 jobs of backend/crontab, a broken job, all pinged as expected"

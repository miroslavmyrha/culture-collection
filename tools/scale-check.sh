#!/usr/bin/env bash
# The main screens' API at two sizes (#71): seed_dev plus 50 strains, then plus 500. Fails when a
# screen's query count grows with the data, or a screen at 500 strains takes longer than
# SCALE_BUDGET_MS (generous: a shared runner is noisy, the budget catches a jump, not a drift).
# Prints both tables; CI appends them to the job summary. Uses the compose stack of this checkout
# and removes its database at the end.
set -euo pipefail
cd "$(dirname "$0")/.."
fail() { echo "FAILED: $1" >&2; exit 1; }
budget=${SCALE_BUDGET_MS:-1500}
export APP_UID="${APP_UID:-$(id -u)}"
password=$(openssl rand -hex 16)
cleanup() { docker compose down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker compose down -v >/dev/null 2>&1 || true
docker compose up -d --wait db >/dev/null || fail "the database did not start"
docker compose build backend >/dev/null || fail "the backend image did not build"
run() { docker compose run --rm -T "$@"; }
run backend sh -c "python manage.py migrate -v0 && python manage.py createcachetable" >/dev/null || fail "migrate"
run -e DEV_PASSWORD="$password" backend python manage.py seed_dev >/dev/null || fail "seed_dev"
run backend python manage.py seed_scale --strains 50 >/dev/null || fail "seed_scale 50"
echo "### 50 strains"
run backend python tools/measure_scale.py --json .reports/scale-small.json || fail "a screen at 50 strains"
run backend python manage.py seed_scale --strains 500 >/dev/null || fail "seed_scale 500"
echo
echo "### 500 strains (query counts as at 50, every screen under ${budget} ms)"
run backend python tools/measure_scale.py --flat-with .reports/scale-small.json --budget-ms "$budget" \
  || fail "a screen's queries grew with the data, or it was over ${budget} ms"
run backend python manage.py audit_reconcile --since 2h >/dev/null || fail "audit_reconcile after the seeds"

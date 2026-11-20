#!/usr/bin/env bash
# A backup restored (#177): deploy/deploy.sh starts the production stack (and takes the backup
# before migrate on the empty database), seed_e2e fills it, deploy/backup.sh run backs it up into
# a local restic repository, check passes, and restore brings the latest set into a second,
# empty stack, where the row counts and the audit chains must match. Then both ways: a restore
# into the stack that has data is refused, a restored stack with a row missing fails on the
# counts, and one with an audit event edited fails on the chain. Last, the running stack is
# replaced by the restore, as the runbook says, and deployed again. Everything is removed after.
#
#   deploy/e2e-restore.sh   E2E_HTTPS_PORT (8643), E2E_HTTP_PORT (8280) move it
set -euo pipefail
cd "$(dirname "$0")"
export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-cultures-e2e-restore}
export HTTPS_PORT=${E2E_HTTPS_PORT:-8643} HTTP_PORT=${E2E_HTTP_PORT:-8280}
export WEB_SUBNET=${E2E_WEB_SUBNET:-10.182.0.0/24} PROXY_ADDRESS=${E2E_PROXY_ADDRESS:-10.182.0.10}
export RESTORE_WEB_SUBNET=${E2E_RESTORE_WEB_SUBNET:-10.183.0.0/24}
export RESTORE_PROXY_ADDRESS=${E2E_RESTORE_PROXY_ADDRESS:-10.183.0.10}
export E2E_PASSWORD=${E2E_PASSWORD:-$(head -c 24 /dev/urandom | base64 | tr -d '/+=\n')}
target=$COMPOSE_PROJECT_NAME-restored
# shellcheck source=e2e-common.sh
. ./e2e-common.sh
in_target() { COMPOSE_PROJECT_NAME=$target WEB_SUBNET=$RESTORE_WEB_SUBNET PROXY_ADDRESS=$RESTORE_PROXY_ADDRESS compose "$@"; }
cleanup() {
  local status=$?
  in_target down -v --remove-orphans >/dev/null 2>&1 || true
  e2e_cleanup "$status"
}
trap cleanup EXIT
# Writes past the guard triggers, as only someone at the database could: replica mode.
tamper() { in_target exec -T db psql -q -U cultures -d cultures -v ON_ERROR_STOP=1 -c "SET session_replication_role = replica; $1"; }

echo "== the stack, with the backup before migrate on its empty database"
./deploy.sh >/dev/null
docker compose -f compose.yaml run --rm -T --no-deps \
  -e DJANGO_SETTINGS_MODULE=config.settings.local -e DJANGO_SECRET_KEY_FILE= -e E2E_PASSWORD \
  backend python manage.py seed_e2e >/dev/null || fail "seed_e2e"

echo "== backup and check"
./backup.sh run
./backup.sh check

echo "== restore into an empty stack"
./backup.sh restore latest --into "$target"

echo "== both ways"
# Each must fail, and for its own reason: the line the check prints names it.
refused() {
  local want=$1 out; shift
  if out=$("$@" 2>&1); then fail "went ahead: $*"; fi
  grep -q "$want" <<<"$out" || fail "$* failed, but not with \"$want\": $(tail -3 <<<"$out")"
}
refused "tables already" ./backup.sh restore latest --into "$COMPOSE_PROJECT_NAME"
tamper "DELETE FROM lineage_vial WHERE id = (SELECT max(id) FROM lineage_vial);"
refused "differ from set" ./backup.sh verify latest --into "$target"
in_target down -v >/dev/null 2>&1
./backup.sh restore latest --into "$target" >/dev/null
tamper "UPDATE audit_auditevent SET reason = reason || ' (edited)' WHERE id = (SELECT min(id) FROM audit_auditevent);"
refused "do not verify" ./backup.sh verify latest --into "$target"

echo "== the running stack replaced by the restore (docs/runbook.md, Restore step 2)"
in_target down -v >/dev/null 2>&1
compose down -v >/dev/null 2>&1
./backup.sh restore latest --into "$COMPOSE_PROJECT_NAME" >/dev/null
./deploy.sh >/dev/null
code=$(curl -ks -o /dev/null -w '%{http_code}' "https://localhost:$HTTPS_PORT/api/v1/auth/csrf/")
[ "$code" = 204 ] || fail "the stack restored in place answers $code through the proxy"
echo "restored and verified; a restore over data, a missing row and an edited event are refused, and the restore replaced the running stack"

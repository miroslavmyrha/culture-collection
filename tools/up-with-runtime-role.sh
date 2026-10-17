#!/usr/bin/env bash
# Start the compose stack the way production runs (ADR 0005, README "Deploy"):
#   1. manage.py db_roles as the admin (compose's superuser) creates the roles;
#   2. the login passwords are set through psql variables, never on a command line;
#   3. migrate and createcachetable run as the migration role, with a lock timeout;
#   4. the API runs as the runtime role, and /readyz must confirm it owns nothing.
# CI runs this before ./check.sh e2e, so the e2e suite runs against the restricted role.
# Development may keep `docker compose up -d` (the API as the owner). Running this
# again is safe. Afterwards `docker compose up -d backend` goes back to the owner.
#
# Passwords: DB_MIGRATION_PASSWORD and DB_RUNTIME_PASSWORD (CI passes random ones).
# Role names: the defaults of DATABASE_ROLES in backend/config/settings/base.py.
set -euo pipefail
cd "$(dirname "$0")/.."
fail() { echo "FAILED: $1" >&2; exit 1; }

export APP_UID="${APP_UID:-$(id -u)}"
export DB_MIGRATION_PASSWORD="${DB_MIGRATION_PASSWORD:-migration-dev-only}"
export DB_RUNTIME_PASSWORD="${DB_RUNTIME_PASSWORD:-runtime-dev-only}"
migration=cultures_migration
runtime=cultures_app
url() { echo "postgres://$1:$2@db:5432/cultures"; }

docker compose up -d --wait db >/dev/null || fail "the database did not start: docker compose logs db"
docker compose build backend >/dev/null || fail "the backend image did not build"

echo "== roles (as the admin)"
# BACKEND_DATABASE_URL empty: compose's default, the superuser.
BACKEND_DATABASE_URL='' docker compose run --rm -T backend python manage.py db_roles \
  || fail "manage.py db_roles"
docker compose exec -T -e DB_MIGRATION_PASSWORD -e DB_RUNTIME_PASSWORD db \
  psql -q -v ON_ERROR_STOP=1 -U cultures -d cultures <<SQL || fail "setting the role passwords"
\getenv migration_password DB_MIGRATION_PASSWORD
\getenv runtime_password DB_RUNTIME_PASSWORD
ALTER ROLE $migration PASSWORD :'migration_password';
ALTER ROLE $runtime PASSWORD :'runtime_password';
SQL

echo "== migrate (as $migration)"
docker compose run --rm -T \
  -e DATABASE_URL="$(url "$migration" "$DB_MIGRATION_PASSWORD")" \
  -e PGOPTIONS='-c lock_timeout=5s' -e DB_APPLICATION_NAME=cultures-migrate \
  backend sh -c 'python manage.py migrate --noinput && python manage.py createcachetable' \
  || fail "migrate as the migration role"

echo "== API (as $runtime)"
BACKEND_DATABASE_URL="$(url "$runtime" "$DB_RUNTIME_PASSWORD")" DB_RUNTIME_ROLE_REQUIRED=true \
  docker compose up -d backend >/dev/null || fail "the backend did not start"
address=$(docker compose port backend 8000) || fail "the backend publishes no port"
for _ in $(seq 30); do
  if curl -fsS "http://localhost:${address##*:}/readyz" >/dev/null 2>&1; then
    echo "ready on :${address##*:}, connected as $runtime"
    exit 0
  fi
  sleep 2
done
curl -sS "http://localhost:${address##*:}/readyz" || true
docker compose logs backend
fail "/readyz did not answer 200: a failing runtime_role check means the API runs as an owner"

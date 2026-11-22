#!/usr/bin/env bash
# Deploy or update the production stack of deploy/compose.yaml (#178, #179), the way
# tools/up-with-runtime-role.sh starts the development one (ADR 0005):
#   1. the images: a release is verified (cosign) and pulled by digest, or both are built here;
#   2. the database, then manage.py db_roles as the admin creates the roles;
#   3. the role passwords are set through psql variables, never on a command line;
#   4. the backup before migrate (deploy/backup.sh, #177), then migrate and createcachetable as
#      the migration role, with a lock timeout;
#   5. the API runs as the runtime role (its health check is /readyz), then the proxy and the
#      scheduler of the jobs (#180), on the API's image.
# Running it again is safe: it is also how an update is deployed.
#
#   deploy/deploy.sh secrets   write any missing secret in deploy/secrets/ (random)
#   deploy/deploy.sh X.Y.Z     deploy the signed release X.Y.Z from GHCR. A release that does not
#                              come up healthy is replaced by the previous one again, and the
#                              script exits non-zero naming the step that failed.
#   deploy/deploy.sh           build both images here and deploy them (no rollback: e2e, trials)
#
# Rollback restores images only. Migrations go forward only: the migration linter of check.sh
# refuses one the previous release could not run on, so the previous release works on the new
# schema. A restore of the backup taken before migrate is the way back from a bad migration.
set -euo pipefail
cd "$(dirname "$0")"
fail() { echo "FAILED: $1" >&2; exit 1; }
compose() { docker compose -f compose.yaml "$@"; }
# ENV_FILE and SECRETS_DIR: another settings file and secrets folder (deploy/e2e-production.sh).
export ENV_FILE=${ENV_FILE:-.env} SECRETS_DIR=${SECRETS_DIR:-./secrets}
secret() { cat "$SECRETS_DIR/$1"; }
# The release the stack runs and the one before it (deploy/state/, VERSION and both image refs).
export STATE_DIR=${STATE_DIR:-./state}
REGISTRY=ghcr.io/miroslavmyrha/culture-collection
# The only identity a release image may be signed by: release.yml of this repository on its tag.
SIGNER=https://github.com/miroslavmyrha/culture-collection/.github/workflows/release.yml
COSIGN_IMAGE=ghcr.io/sigstore/cosign/cosign:v3.1.4@sha256:0f06154836d2de34f887a5c273506d52ca43edaa1d9e53e6510fa78a48f69c2d

if [ "${1:-}" = secrets ]; then
  # The folder is the lock (mode 700, only its owner opens it on the host). The files are 644:
  # compose mounts them with the host's owner and mode, and the API runs as uid 10001.
  umask 077
  mkdir -p "$SECRETS_DIR"
  chmod 700 "$SECRETS_DIR"
  for name in db_admin_password db_migration_password db_runtime_password django_secret_key mfa_secret_key restic_password; do
    [ -s "$SECRETS_DIR/$name" ] || head -c 48 /dev/urandom | base64 | tr -d '/+=\n' > "$SECRETS_DIR/$name"
  done
  [ -s "$SECRETS_DIR/database_url" ] \
    || echo "postgres://cultures_app:$(secret db_runtime_password)@db:5432/cultures" > "$SECRETS_DIR/database_url"
  # The Healthchecks ping URL with its key (#180), empty until the operator fills it in: the
  # scheduled jobs then run and report nothing (docs/runbook.md "Scheduled jobs and alerts").
  [ -e "$SECRETS_DIR/healthchecks_ping_url" ] || : > "$SECRETS_DIR/healthchecks_ping_url"
  chmod 644 "$SECRETS_DIR"/*
  echo "secrets in $SECRETS_DIR: keep a copy OFF THE HOST. Without restic_password no backup can"
  echo "be read (deploy/backup.sh, docs/runbook.md)."
  exit 0
fi

[ -f "$ENV_FILE" ] || fail "no $ENV_FILE: copy deploy/.env.example to deploy/.env and fill it in"
for name in db_admin_password db_migration_password db_runtime_password django_secret_key mfa_secret_key database_url; do
  [ -s "$SECRETS_DIR/$name" ] || fail "no $SECRETS_DIR/$name: run deploy/deploy.sh secrets"
done
[ "$(stat -c %a "$SECRETS_DIR")" = 700 ] || fail "$SECRETS_DIR must be mode 700: chmod 700 $SECRETS_DIR"
# A deployment from before #180 has no ping URL file yet: compose needs the file, empty is fine.
[ -e "$SECRETS_DIR/healthchecks_ping_url" ] || install -m 644 /dev/null "$SECRETS_DIR/healthchecks_ping_url"
# compose reads TLS_DIR and the ports from the shell or deploy/.env (its project .env file).
tls_dir=${TLS_DIR:-$(grep -E '^TLS_DIR=' .env 2>/dev/null | cut -d= -f2- || true)}
for file in fullchain.pem privkey.pem; do
  [ -s "${tls_dir:-./certs}/$file" ] || fail "no ${tls_dir:-./certs}/$file: the proxy needs the certificate"
done

version=${1:-}
release=false
if [ -n "$version" ]; then
  [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "usage: deploy/deploy.sh [secrets | X.Y.Z]"
  release=true
fi

state_value() { grep -E "^$1=" "$2" | cut -d= -f2-; }

# The release that ran before this deploy starts again: images only (see the top).
rollback() {
  local previous=$STATE_DIR/current
  if [ ! -s "$previous" ]; then
    echo "no earlier release recorded in $STATE_DIR: nothing to roll back to" >&2
    return
  fi
  local back
  back=$(state_value VERSION "$previous")
  echo "== rollback to $back" >&2
  if BACKEND_IMAGE=$(state_value BACKEND_IMAGE "$previous") PROXY_IMAGE=$(state_value PROXY_IMAGE "$previous") \
    compose up -d --no-build --wait --wait-timeout 180 backend proxy scheduler >/dev/null; then
    echo "rolled back: $back runs" >&2
  else
    echo "ROLLBACK FAILED: the stack is down. Look at the logs, then deploy/deploy.sh $back" >&2
  fi
}

# A failed step of a release rolls back first; a local build only stops.
step_failed() {
  if $release; then
    echo "FAILED: release $version: $1" >&2
    rollback
    exit 1
  fi
  fail "$1"
}

# The signed image of a release, by the digest its signature covers.
verified() {
  local ref=$REGISTRY-$1:$version out digest
  out=$(docker run --rm "$COSIGN_IMAGE" verify \
    --certificate-identity "$SIGNER@refs/tags/v$version" \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com "$ref" 2>/dev/null) \
    || fail "the signature of $ref does not verify: nothing was deployed"
  digest=$(grep -o '"docker-manifest-digest":"sha256:[0-9a-f]*"' <<<"$out" | head -1 | cut -d'"' -f4)
  [ -n "$digest" ] || fail "no digest in the signature of $ref"
  docker pull -q "$REGISTRY-$1@$digest" >/dev/null || fail "pulling $REGISTRY-$1@$digest"
  echo "$REGISTRY-$1@$digest"
}

echo "== images"
if ! $release; then
  compose build backend proxy >/dev/null || fail "the images did not build"
elif [ "${LOCAL_RELEASE:-}" = 1 ]; then
  # Tests only (deploy/e2e-rollback.sh): images built here under local/, never verified. A
  # version from the registry is always verified: this branch cannot name one.
  echo "LOCAL_RELEASE: local/culture-collection-*:$version, not verified" >&2
  export BACKEND_IMAGE=local/culture-collection-backend:$version
  export PROXY_IMAGE=local/culture-collection-proxy:$version
  for ref in "$BACKEND_IMAGE" "$PROXY_IMAGE"; do
    docker image inspect "$ref" >/dev/null 2>&1 || fail "no local image $ref"
  done
else
  BACKEND_IMAGE=$(verified backend) || exit 1
  PROXY_IMAGE=$(verified proxy) || exit 1
  export BACKEND_IMAGE PROXY_IMAGE
  echo "verified: $BACKEND_IMAGE $PROXY_IMAGE"
fi
# From here on a release that fails rolls back.

echo "== database"
compose up -d --wait db >/dev/null || step_failed "the database did not start: docker compose -f deploy/compose.yaml logs db"

# The URLs carry passwords: they reach the containers through this script's environment
# (docker compose run -e NAME), never through its arguments.
export DATABASE_URL_FILE=''
export DB_MIGRATION_PASSWORD DB_RUNTIME_PASSWORD
DB_MIGRATION_PASSWORD=$(secret db_migration_password)
DB_RUNTIME_PASSWORD=$(secret db_runtime_password)

echo "== roles (as the admin)"
DATABASE_URL="postgres://cultures:$(secret db_admin_password)@db:5432/cultures" \
  compose run --rm -T --no-deps -e DATABASE_URL_FILE -e DATABASE_URL backend python manage.py db_roles \
  || step_failed "manage.py db_roles"
compose exec -T -e DB_MIGRATION_PASSWORD -e DB_RUNTIME_PASSWORD db \
  psql -q -v ON_ERROR_STOP=1 -U cultures -d cultures <<'SQL' || step_failed "setting the role passwords"
\getenv migration_password DB_MIGRATION_PASSWORD
\getenv runtime_password DB_RUNTIME_PASSWORD
ALTER ROLE cultures_migration PASSWORD :'migration_password';
ALTER ROLE cultures_app PASSWORD :'runtime_password';
SQL

echo "== backup before migrate"
# deploy/backup.sh (#177): the backup a bad migration is restored from. No backup, no migrate.
./backup.sh before-migrate || step_failed "the backup before migrate"

echo "== migrate (as cultures_migration)"
DATABASE_URL="postgres://cultures_migration:${DB_MIGRATION_PASSWORD}@db:5432/cultures" \
  compose run --rm -T --no-deps -e DATABASE_URL_FILE -e DATABASE_URL \
  -e PGOPTIONS='-c lock_timeout=5s' -e DB_APPLICATION_NAME=cultures-migrate \
  backend sh -c 'python manage.py migrate --noinput && python manage.py createcachetable' \
  || step_failed "migrate as the migration role"

echo "== API, proxy and scheduler"
compose up -d --no-build --wait --wait-timeout 180 backend proxy scheduler >/dev/null \
  || step_failed "the stack is not healthy: docker compose -f deploy/compose.yaml ps, then logs backend proxy scheduler"

if $release; then
  mkdir -p "$STATE_DIR"
  [ -s "$STATE_DIR/current" ] && mv "$STATE_DIR/current" "$STATE_DIR/previous"
  printf 'VERSION=%s\nBACKEND_IMAGE=%s\nPROXY_IMAGE=%s\n' "$version" "$BACKEND_IMAGE" "$PROXY_IMAGE" \
    > "$STATE_DIR/current"
fi
echo "deployed${version:+ $version}: $(compose ps --format '{{.Service}} {{.Status}}' | tr '\n' ',' | sed 's/,$//')"

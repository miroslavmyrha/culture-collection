#!/usr/bin/env bash
# Backups of the production database with restic (#177). The documents live in the database,
# so the database is all the data.
#
#   deploy/backup.sh init                     create the restic repository (once)
#   deploy/backup.sh run                      the scheduled backup, then the retention
#   deploy/backup.sh before-migrate           the backup deploy/deploy.sh takes before migrate
#   deploy/backup.sh check                    restic check, and the newest backup younger than
#                                             BACKUP_MAX_AGE_HOURS (26)
#   deploy/backup.sh restore SET|latest [--into PROJECT]
#                                             restore into an empty stack, then verify it
#   deploy/backup.sh verify SET|latest [--into PROJECT]
#                                             verify a restored stack against its backup
#
# A backup is one set of three files, each a restic snapshot tagged set=<time>: roles.sql
# (pg_dumpall --roles-only: the roles of ADR 0005 exist before the data), cultures.dump
# (pg_dump, custom format) and manifest.txt (the release, and the row counts of the tables
# below). All three come from one exported database snapshot, so the counts are the counts of
# the dump. The manifest is written last: a set without one is incomplete and never restored.
# Nothing is written to the host's disk on the way: pg_dump streams into restic.
#
# The repository is configuration: RESTIC_REPOSITORY in deploy/.env (an S3 bucket in the EU,
# sftp:, or a local path for tests). The restic password is secrets/restic_password, and
# secrets/restic_env holds the repository's credentials (AWS_ACCESS_KEY_ID=..., one per line)
# when it needs any. KEEP A COPY OF THE RESTIC PASSWORD OFF THE HOST: without it no backup can
# be read, and the host is what a backup has to survive.
set -euo pipefail
cd "$(dirname "$0")"
fail() { echo "FAILED: $1" >&2; exit 1; }
export ENV_FILE=${ENV_FILE:-.env} SECRETS_DIR=${SECRETS_DIR:-./secrets} STATE_DIR=${STATE_DIR:-./state}
compose() { docker compose -f compose.yaml "$@"; }
RESTIC_IMAGE=restic/restic:0.20.0@sha256:93999df80d4ac6cb148e82d2ef1fe6a81996f17ff535e772723538211b31555a
# What a restore must bring back, counted in the backup and again after the restore.
TABLES=(users_user labs_lab strains_strain lineage_vial distribution_document
  audit_auditevent audit_rowchange audit_chainanchor)
MAX_AGE_HOURS=${BACKUP_MAX_AGE_HOURS:-26}

setting() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true; }
repository=${RESTIC_REPOSITORY:-$(setting RESTIC_REPOSITORY)}
[ -n "$repository" ] || fail "no RESTIC_REPOSITORY in $ENV_FILE: where do the backups go?"
[ -s "$SECRETS_DIR/restic_password" ] || fail "no $SECRETS_DIR/restic_password: run deploy/deploy.sh secrets"

# restic in its own container: the host's uid (a local repository stays the operator's),
# read-only, no capabilities, the cache on a tmpfs.
restic() {
  local extra=()
  [ -s "$SECRETS_DIR/restic_env" ] && extra+=(--env-file "$SECRETS_DIR/restic_env")
  case $repository in /*) extra+=(-v "$repository:$repository") ;; esac
  docker run --rm -i --user "$(id -u):$(id -g)" --read-only --tmpfs /tmp \
    --cap-drop ALL --security-opt no-new-privileges:true \
    -e RESTIC_REPOSITORY="$repository" -e RESTIC_PASSWORD_FILE=/run/restic/password \
    -e RESTIC_CACHE_DIR=/tmp/cache -e RESTIC_PROGRESS_FPS=0 \
    -v "$(realpath "$SECRETS_DIR/restic_password"):/run/restic/password:ro" \
    --hostname cultures "${extra[@]}" "$RESTIC_IMAGE" -q "$@"
}

# The row counts of TABLES (and a digest of the documents' sha256 values), one line each, as
# one statement: in a transaction it sees that transaction's snapshot.
count_query() {
  local table parts=()
  for table in "${TABLES[@]}"; do
    parts+=("SELECT 'count $table ' || CASE WHEN to_regclass('public.$table') IS NULL THEN 'absent'
      ELSE (xpath('/row/c/text()', query_to_xml('SELECT count(*) AS c FROM public.$table', false, true, '')))[1]::text END")
  done
  parts+=("SELECT 'documents ' || CASE WHEN to_regclass('public.distribution_document') IS NULL THEN 'absent'
    ELSE (xpath('/row/d/text()', query_to_xml('SELECT md5(coalesce(string_agg(sha256, '','' ORDER BY id), '''')) AS d FROM public.distribution_document', false, true, '')))[1]::text END")
  local IFS=$'\n'
  echo "${parts[*]/%/ UNION ALL}" | sed '$ s/ UNION ALL$/;/'
}

backup() {
  local reason=$1 set version
  set=$(date -u +%Y%m%dT%H%M%SZ)
  version=$(grep -E '^VERSION=' "$STATE_DIR/current" 2>/dev/null | cut -d= -f2- || true)
  local tags="cultures,set=$set,reason=$reason,release=${version:-local}"
  echo "== backup $set ($reason)"
  # One session holds a repeatable read transaction open: its exported snapshot is what
  # pg_dump reads, and the counts come from the same snapshot.
  coproc SNAPSHOT { compose exec -T db psql -U cultures -d cultures -qAtX -v ON_ERROR_STOP=1; }
  echo "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();" >&"${SNAPSHOT[1]}"
  local snapshot
  read -t 60 -r snapshot <&"${SNAPSHOT[0]}" || fail "the database exported no snapshot"
  local manifest="release ${version:-local}"$'\n'"taken $set"$'\n'"reason $reason"
  count_query >&"${SNAPSHOT[1]}"
  local line
  for _ in $(seq $((${#TABLES[@]} + 1))); do
    read -t 120 -r line <&"${SNAPSHOT[0]}" || fail "the counts did not come"
    manifest+=$'\n'"$line"
  done
  compose exec -T db pg_dumpall -U cultures --roles-only \
    | restic backup --stdin --stdin-filename roles.sql --tag "$tags" \
    || fail "the roles did not reach the repository"
  compose exec -T db pg_dump -U cultures -d cultures -Fc --snapshot="$snapshot" \
    | restic backup --stdin --stdin-filename cultures.dump --tag "$tags" \
    || fail "the dump did not reach the repository"
  echo "COMMIT;" >&"${SNAPSHOT[1]}"
  local session=$SNAPSHOT_PID input=${SNAPSHOT[1]}
  exec {input}>&-
  wait "$session" || true
  printf '%s\n' "$manifest" | restic backup --stdin --stdin-filename manifest.txt --tag "$tags" \
    || fail "the manifest did not reach the repository"
  echo "backup $set: $(grep -c '^count ' <<<"$manifest") tables counted"
}

# The set a name stands for: latest is the newest set with a manifest.
resolve_set() {
  if [ "$1" != latest ]; then echo "$1"; return; fi
  sets | tail -1
}

# The complete sets, oldest first: the set tags are UTC times, so they sort.
sets() {
  restic snapshots --tag cultures --path /manifest.txt --json \
    | grep -o '"set=[0-9TZ]*"' | tr -d '"' | cut -d= -f2 | sort -u
}

file_of() { restic dump --tag "set=$1" --path "/$2" latest "/$2"; }

# Parse --into PROJECT after the set; the default is a project of its own, never the live one.
target_project() {
  local into=cultures-restore
  while [ $# -gt 0 ]; do
    case $1 in --into) into=${2:?--into needs a project name}; shift 2 ;; *) fail "unknown argument $1" ;; esac
  done
  echo "$into"
}

# Compose for the restored stack: its own project and volume. A stack of its own also gets a
# web network of its own, which may not overlap the running one's. Restored into the running
# project (docs/runbook.md, after `down -v`), it keeps that project's network, which
# deploy/deploy.sh then finds as it left it.
restored() {
  local live=${COMPOSE_PROJECT_NAME:-cultures}
  if [ "$project" = "$live" ]; then
    DJANGO_ADMIN_PATH=${DJANGO_ADMIN_PATH:-restore/} docker compose -f compose.yaml "$@"
  else
    COMPOSE_PROJECT_NAME=$project WEB_SUBNET=${RESTORE_WEB_SUBNET:-10.181.0.0/24} \
      PROXY_ADDRESS=${RESTORE_PROXY_ADDRESS:-10.181.0.10} DJANGO_ADMIN_PATH=${DJANGO_ADMIN_PATH:-restore/} \
      docker compose -f compose.yaml "$@"
  fi
}

restore() {
  local set=$1
  echo "== restore $set into project $project"
  restored up -d --wait db >/dev/null || fail "the database of $project did not start"
  local tables
  tables=$(restored exec -T db psql -U cultures -d cultures -qAtX -c \
    "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
  [ "$tables" = 0 ] || fail "project $project has $tables tables already: a restore goes into an empty stack (docs/runbook.md)"
  file_of "$set" manifest.txt >/dev/null || fail "set $set has no manifest: it is incomplete"
  # The admin role of the new database exists already: the dump's lines for it are left out.
  file_of "$set" roles.sql | grep -vE '^(CREATE|ALTER) ROLE cultures( |;)' \
    | restored exec -T db psql -q -U cultures -d postgres -v ON_ERROR_STOP=1 >/dev/null \
    || fail "the roles of set $set did not restore"
  file_of "$set" cultures.dump \
    | restored exec -T db pg_restore -U cultures -d cultures --exit-on-error --single-transaction \
    || fail "the dump of set $set did not restore"
  # The passwords are those of this host's secrets, as deploy/deploy.sh sets them.
  DB_MIGRATION_PASSWORD=$(cat "$SECRETS_DIR/db_migration_password") \
    DB_RUNTIME_PASSWORD=$(cat "$SECRETS_DIR/db_runtime_password") \
    restored exec -T -e DB_MIGRATION_PASSWORD -e DB_RUNTIME_PASSWORD db \
    psql -q -v ON_ERROR_STOP=1 -U cultures -d cultures <<'SQL' >/dev/null || fail "setting the role passwords"
\getenv migration_password DB_MIGRATION_PASSWORD
\getenv runtime_password DB_RUNTIME_PASSWORD
ALTER ROLE cultures_migration PASSWORD :'migration_password';
ALTER ROLE cultures_app PASSWORD :'runtime_password';
SQL
  echo "restored set $set into $project"
}

verify() {
  local set=$1 expected actual
  echo "== verify $project against set $set"
  expected=$(file_of "$set" manifest.txt | grep -E '^(count|documents) ') || fail "set $set has no manifest"
  actual=$(count_query | restored exec -T db psql -U cultures -d cultures -qAtX -v ON_ERROR_STOP=1) \
    || fail "counting the rows of $project"
  if [ "$expected" != "$actual" ]; then
    diff <(echo "$expected") <(echo "$actual") >&2 || true
    fail "the rows of $project differ from set $set (left: the backup, right: the restore)"
  fi
  echo "rows: $(grep -c '^count ' <<<"$actual") tables and the documents as in the backup"
  restored run --rm -T --no-deps backend python manage.py audit_chain_verify \
    || fail "the audit chains of $project do not verify"
  echo "verified: $project holds set $set"
}

mode=${1:-}
case $mode in
  init)
    if restic cat config >/dev/null 2>&1; then echo "the repository exists"; else restic init; fi ;;
  run)
    backup scheduled
    restic forget --tag cultures --group-by paths --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune ;;
  before-migrate)
    backup before-migrate ;;
  check)
    restic check
    newest=$(sets | tail -1)
    [ -n "$newest" ] || fail "no complete backup in the repository"
    # 20261120T042425Z -> 2026-11-20 04:24:25 UTC
    taken=$(sed -E 's/^(....)(..)(..)T(..)(..)(..)Z$/\1-\2-\3 \4:\5:\6 UTC/' <<<"$newest")
    age=$(( ($(date -u +%s) - $(date -u -d "$taken" +%s)) / 3600 ))
    [ "$age" -lt "$MAX_AGE_HOURS" ] || fail "the newest backup is $age hours old (limit $MAX_AGE_HOURS)"
    echo "the newest backup is $age hours old" ;;
  restore|verify)
    [ $# -ge 2 ] || fail "usage: deploy/backup.sh $mode SET|latest [--into PROJECT]"
    set=$(resolve_set "$2")
    [ -n "$set" ] || fail "no complete backup in the repository"
    project=$(target_project "${@:3}")
    [ "$mode" = verify ] || restore "$set"
    verify "$set" ;;
  *)
    fail "usage: deploy/backup.sh init | run | before-migrate | check | restore SET|latest [--into PROJECT] | verify SET|latest [--into PROJECT]" ;;
esac

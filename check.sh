#!/usr/bin/env bash
# Verification before every commit. Levels:
#   ./check.sh        secrets, migrations, API contract, lint, types, tests (both sides)
#   ./check.sh e2e    plus Playwright against the real API (backend running, test user seeded)
#   ./check.sh audit  plus known-vulnerability audit of Python and npm dependencies (network)
# Each failure says what to run to fix it.
set -euo pipefail
cd "$(dirname "$0")"
level=${1:-}
fail() { echo "FAILED: $1" >&2; exit 1; }
GITLEAKS_IMAGE=ghcr.io/gitleaks/gitleaks:v8.30.1

echo "== secrets"
if git rev-parse --git-dir >/dev/null 2>&1; then
  # tracked changes, then staged ones (new files are only seen once staged; the hook scans staged)
  for mode in "" "--staged"; do
    docker run --rm -v "$PWD:/repo" -w /repo "$GITLEAKS_IMAGE" git --pre-commit $mode --no-banner --redact . >/dev/null 2>&1 \
      || fail "possible secret in uncommitted changes: run docker run --rm -v \"\$PWD:/repo\" -w /repo $GITLEAKS_IMAGE git --pre-commit $mode --redact ."
  done
else
  echo "(not a git repository, skipped)"
fi

echo "== backend"
# The dev container writes caches into the ./backend bind mount: build it with the caller's uid.
export APP_UID="${APP_UID:-$(id -u)}"
docker compose up -d db >/dev/null || fail "the database did not start: docker compose logs db"
# Each step stops the run with its own FAILED line. No `a && b` chains: set -e
# ignores a failure inside one, so a ruff failure would skip mypy and leave the
# exit code to pytest alone.
docker compose run --rm -T -e DJANGO_SETTINGS_MODULE=config.settings.test backend sh -c '
  set -eu
  fail() { echo "FAILED: $1" >&2; exit 1; }
  ruff format --check . || fail "ruff format: run ruff format ."
  ruff check . || fail "ruff check: fix the findings above (ruff check --fix applies the safe ones)"
  mypy . || fail "mypy: fix the type errors above"
  python manage.py makemigrations --check --dry-run >/dev/null || fail "models changed without a migration: run makemigrations"
  # --no-cache: a cached result reports warnings without failing, even with --warnings-as-errors.
  python manage.py lintmigrations --no-cache -q ok ignore --warnings-as-errors \
    || fail "risky migration (see above): split it into safe steps or mark it ignored with a reason"
  python manage.py spectacular --file /tmp/openapi.yml --validate --fail-on-warn \
    || fail "the API schema does not validate (see above)"
  cmp -s openapi.yml /tmp/openapi.yml || fail "API schema out of date: run ./sync-api.sh"
  # Production settings must load and pass the deploy checks (throwaway values, behind a TLS proxy).
  DJANGO_SETTINGS_MODULE=config.settings.production \
  DJANGO_SECRET_KEY="$(python -c "import secrets; print(secrets.token_urlsafe(64))")" \
  DJANGO_ALLOWED_HOSTS=app.example.com DJANGO_ADMIN_PATH=ops-check/ \
  DJANGO_BEHIND_TLS_PROXY=true DJANGO_NUM_PROXIES=1 \
    python manage.py check --deploy --fail-level WARNING >/dev/null \
    || fail "production settings fail check --deploy: run it with DJANGO_SETTINGS_MODULE=config.settings.production"
  pytest -q -p no:cacheprovider || fail "pytest: tests failed (see above)"
'
if [ "$level" = "audit" ]; then
  docker compose run --rm -T backend pip-audit || fail "vulnerable Python dependency (see above)"
fi

echo "== frontend"
(
  cd frontend
  # The generator pinned in package.json (npm run api:types uses the same one).
  npx openapi-typescript ../backend/openapi.yml -o /tmp/schema.d.ts >/dev/null 2>&1 \
    || fail "openapi-typescript could not read backend/openapi.yml: run npm ci, then ./sync-api.sh"
  cmp -s src/api/schema.d.ts /tmp/schema.d.ts || fail "TypeScript API types out of date: run ./sync-api.sh"
  npm run check || fail "frontend check (tsc, oxlint, vitest): see above"
  if [ "$level" = "audit" ]; then npm audit --audit-level=high || fail "vulnerable npm dependency (see above)"; fi
  if [ "$level" = "e2e" ]; then npx playwright test || fail "Playwright e2e (see above)"; fi
)
echo "all checks passed"

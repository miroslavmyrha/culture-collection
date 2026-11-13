#!/usr/bin/env bash
# Verification before every commit. Levels:
#   ./check.sh        secrets, static analysis, migrations, API contract, lint, types, tests and the
#                     code risk score of every function (both sides)
#   ./check.sh e2e    plus Playwright against the real API (backend running, test user seeded)
#   ./check.sh audit  plus known-vulnerability audit of Python and npm dependencies (network)
# Each failure says what to run to fix it.
set -euo pipefail
cd "$(dirname "$0")"
level=${1:-}
fail() { echo "FAILED: $1" >&2; exit 1; }
GITLEAKS_IMAGE=ghcr.io/gitleaks/gitleaks:v8.30.1
SEMGREP_IMAGE=semgrep/semgrep:1.179.0@sha256:93963d9295a366f59e4850127b1550400ee7b388f04fe144e4a1f6325d96e01b

echo "== secrets"
if git rev-parse --git-dir >/dev/null 2>&1; then
  # In a linked worktree .git is a file that points into the main checkout's .git: mount that
  # directory too, at the same absolute paths, or gitleaks cannot open the repository.
  common=$(cd "$(git rev-parse --git-common-dir)" && pwd)
  # tracked changes, then staged ones (new files are only seen once staged; the hook scans staged)
  for mode in "" "--staged"; do
    out=$(docker run --rm -v "$PWD:$PWD" -v "$common:$common" -w "$PWD" "$GITLEAKS_IMAGE" \
      git --pre-commit $mode --no-banner --redact . 2>&1) \
      || fail "possible secret in uncommitted changes: run docker run --rm -v \"\$PWD:\$PWD\" -v \"$common:$common\" -w \"\$PWD\" $GITLEAKS_IMAGE git --pre-commit $mode --redact ."
    # gitleaks exits 0 when git fails, after scanning nothing: treat that as a failure.
    case "$out" in
      *"fatal:"* | *"not a git repository"*) fail "gitleaks could not read the git repository: $out" ;;
    esac
  done
else
  echo "(not a git repository, skipped)"
fi

echo "== static analysis"
# Rules for known Django and DRF traps (tools/semgrep). ERROR and WARNING fail, INFO findings
# are review prompts and are not reported here. Only backend/ and the rules are mounted: in a
# linked worktree .git points outside the mount, and Semgrep's git calls fail noisily.
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/backend:/src:ro" \
  -v "$PWD/tools/semgrep:/rules:ro" -w /src "$SEMGREP_IMAGE" \
  semgrep scan --metrics=off --disable-version-check --quiet --error \
  --severity ERROR --severity WARNING --config /rules . \
  || fail "static analysis: fix the findings above, or mark one line with # nosemgrep: <rule-id> and the reason"

echo "== CI"
# The e2e job must run the API as the runtime role (ADR 0005), as production does.
grep -Eq '^ +tools/up-with-runtime-role\.sh *$' .github/workflows/ci.yml \
  || fail "ci.yml must start the API with tools/up-with-runtime-role.sh before the e2e tests"
# A gate nothing guards is a gate anyone can drop: the changelog job must stay (#206).
grep -Eq '^  changelog:$' .github/workflows/ci.yml \
  || fail "ci.yml must keep the changelog job: a pull request that changes code adds its CHANGELOG.md line"

echo "== backend"
# The dev container writes caches into the ./backend bind mount: build it with the caller's uid.
export APP_UID="${APP_UID:-$(id -u)}"
docker compose up -d db >/dev/null || fail "the database did not start: docker compose logs db"
# Each step stops the run with its own FAILED line. No `a && b` chains: set -e
# ignores a failure inside one, so a ruff failure would skip mypy and leave the
# exit code to pytest alone.
# The tests create a database and roles: they connect as the owner, whatever role
# the running API uses (the empty values select compose's defaults).
BACKEND_DATABASE_URL='' DB_RUNTIME_ROLE_REQUIRED='' \
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
  DJANGO_BEHIND_TLS_PROXY=true DJANGO_TRUSTED_PROXIES=192.0.2.10 \
    python manage.py check --deploy --fail-level WARNING >/dev/null \
    || fail "production settings fail check --deploy: run it with DJANGO_SETTINGS_MODULE=config.settings.production"
  # The data file goes to /tmp: the working directory is the bind mount of ./backend.
  COVERAGE_FILE=/tmp/.coverage coverage run --source=. -m pytest -q -p no:cacheprovider || fail "pytest: tests failed (see above)"
  # The code risk score (#196): no function over 10, and nothing left unmeasured.
  COVERAGE_FILE=/tmp/.coverage coverage json -q -o /tmp/py-coverage.json
  radon cc -j /app > /tmp/py-radon.json
  python tools/crap.py --py-coverage /tmp/py-coverage.json --py-radon /tmp/py-radon.json --top 5 --gate 10 \
    || fail "code risk: the function named above scores over 10 or was not measured; cover its branches with tests or split it (CONTRIBUTING.md)"
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
  # npm run check, with the coverage the code risk score needs (#196).
  npm run typecheck || fail "tsc: fix the type errors above"
  npm run lint || fail "oxlint: fix the findings above"
  risk=$(mktemp -d)
  npx vitest run --coverage.enabled --coverage.provider=v8 --coverage.reporter=json \
    --coverage.include='src/**' --coverage.reportsDirectory="$risk/coverage" \
    || fail "vitest: tests failed (see above)"
  printf '{"rules":{"complexity":["warn",{"max":1}]}}' > "$risk/oxlint.json"
  npx oxlint -c "$risk/oxlint.json" -f json src > "$risk/complexity.json" || true
  python3 ../backend/tools/crap.py --ts-coverage "$risk/coverage/coverage-final.json" \
    --ts-complexity "$risk/complexity.json" --ts-root "$PWD" --top 5 --gate 10 \
    || fail "code risk: the function named above scores over 10 or was not measured; cover its branches with tests or split it (CONTRIBUTING.md)"
  rm -rf "$risk"
  if [ "$level" = "audit" ]; then npm audit --audit-level=high || fail "vulnerable npm dependency (see above)"; fi
  if [ "$level" = "e2e" ]; then npx playwright test || fail "Playwright e2e (see above)"; fi
)
echo "all checks passed"

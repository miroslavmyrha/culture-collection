#!/usr/bin/env bash
# Regenerate the API contract after backend API changes: openapi.yml, then the TypeScript types.
set -euo pipefail
cd "$(dirname "$0")"
docker compose run --rm -T backend python manage.py spectacular --file openapi.yml --validate --fail-on-warn
(cd frontend && npm run api:types >/dev/null)
echo "openapi.yml and frontend/src/api/schema.d.ts updated"

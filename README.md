# cultures

Django + DRF API (`backend/`) and React + TypeScript SPA (`frontend/`).

## Contributing
Git flow, branch names, commit messages and releases: [CONTRIBUTING.md](CONTRIBUTING.md).

## Run
```bash
docker compose up -d                 # PostgreSQL + API on :8000 (BACKEND_PORT, DB_PORT to change), creates the cache table
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
cd frontend && npm install && npm run dev   # SPA on :5173, /api proxied to the backend
```
Set `VITE_API_PROXY` when the backend is not on `http://localhost:8000`.

## Check
```bash
tools/install-hooks.sh   # once per clone: secrets + ./check.sh, commit message and branch name checks
./check.sh               # secrets, migrations, API contract, lint, types, tests
./check.sh e2e           # plus Playwright against the real API (backend running)
./check.sh audit         # plus pip-audit and npm audit (network)
```

## API contract
After changing the backend API run `./sync-api.sh` (regenerates openapi.yml and the TypeScript types); `./check.sh` fails while they are stale.

## Production image
`backend/Dockerfile` builds the runtime image by default: production dependencies
only (`uv sync --locked --no-dev`), code owned by root and read-only for the app
user (uid 10001), static files collected at build, gunicorn configured from
`GUNICORN_*` variables (`backend/gunicorn.conf.py`). Compose uses the `dev` target.

```bash
docker build -t cultures-api backend
docker run --read-only --tmpfs /tmp -p 8000:8000 --env-file prod.env cultures-api
```

Deploy steps, in order: `python manage.py migrate`, `python manage.py createcachetable`,
then start the new image. Probes: `/healthz` (liveness, no dependencies) and
`/readyz` (database, cache, no unapplied migrations; 503 lists the failing checks).
Both answer any Host header, so a probe can use the pod IP.

Required environment: `DJANGO_SECRET_KEY` (or `DJANGO_SECRET_KEY_FILE`), `DATABASE_URL`
(or `DATABASE_URL_FILE`), `DJANGO_ALLOWED_HOSTS`, `DJANGO_ADMIN_PATH` (not the default).
Behind a TLS proxy: `DJANGO_BEHIND_TLS_PROXY=true`, `DJANGO_NUM_PROXIES` (proxies that
append to X-Forwarded-For, usually 1) and `GUNICORN_FORWARDED_ALLOW_IPS` (the proxy
address). Optional: `DJANGO_SECRET_KEY_FALLBACKS` (key rotation), `LOG_FORMAT=json`,
`ERROR_REPORTING_DSN` (add `sentry-sdk` first), `THROTTLE_*`, `LOGIN_ACCOUNT_*`,
`DATA_UPLOAD_MAX_MEMORY_SIZE`. Startup refuses unsafe values; `./check.sh` runs
`check --deploy` with production settings.

The proxy must cap the request body (`client_max_body_size`): Django limits form
and JSON bodies but not the total size of uploaded files.

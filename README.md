# culture-collection

A simulation, not a production application: no collection runs it, the data is invented, and nobody from a real collection or an authority has reviewed it. It is built to the quality of one that would run in production: security, audit trail, tests and deployment are part of the scope, not an afterthought. It started as a project for learning React. The domain is a culture collection: microbial strains, their storage, preservation and distribution, with a Django + DRF API (`backend/`) and a React + TypeScript SPA (`frontend/`).

## Contributing
Git flow, branch names, commit messages and releases: [CONTRIBUTING.md](CONTRIBUTING.md).

## Run
```bash
# If `id -u` is not 1000, export APP_UID=$(id -u) first: the container writes in ./backend.
docker compose up -d                 # PostgreSQL + API on :8000 (BACKEND_PORT, DB_PORT to change), creates the cache table
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
cd frontend && npm install && npm run dev   # SPA on :5173, /api proxied to the backend
```
Set `VITE_API_PROXY` when the backend is not on `http://localhost:8000`.

The API above connects as the table owner. To run it the way production does, with the
database roles of ADR 0005 (migrations as `cultures_migration`, the API as the runtime
role `cultures_app`, `/readyz` checking that it owns nothing):
```bash
tools/up-with-runtime-role.sh        # idempotent, and how CI runs the e2e suite
docker compose up -d backend         # back to the owner
```

## Development data
To click through the app with more than an empty lab, fill the local database:
```bash
docker compose exec -e DEV_PASSWORD='dev correct horse battery' backend python manage.py seed_dev
```
It creates, all through the services and the audit trail:
- four labs: Bacteriology (BAC), Mycology (MYC), Regulated agents (REG) and
  Environmental isolates (ENV), each with a manager, a curator, a technician and a
  viewer (`bac-manager`, `bac-curator`, ...);
- `dev-admin` (staff and superuser, for Django admin), `dev-two-labs` (curator of BAC,
  viewer of MYC), `dev-no-lab` and `dev-inactive` (deactivated). Every user has the
  password from `DEV_PASSWORD` (or `--password`), and the command prints the logins;
- permits with invented references: MYC holds a valid ÚKZÚZ permit and an ended one, REG
  a valid SÚJB permit, ENV only an expired SÚJB permit, so a VRAT strain is refused there;
- taxa: real bacteria and fungi with their authorities, synonyms and NCBI ids, and the
  invented Testella, Mockia and Fictivibrio;
- 55 strains: some reclassified, some restricted. Restrictions and risk groups that
  matter for the gates are on invented taxa only;
- three box types and a storage tree per lab: freezers and LN2 tanks with racks and
  boxes. REG has a box capped below its freezer's risk group, ENV a freezer out of service.

`backend/cultures/strains/management/commands/seed_dev.json` holds the box types, labs,
storage, taxa and strains, with the source of every fact about a real organism (LPSN, Index Fungorum, NCBI
Taxonomy, nařízení vlády 361/2007 Sb. Příloha 7 and the DSMZ catalogue for risk groups).

A second run finds what exists and changes nothing. It runs only with DEBUG on and the
development settings (`config.settings.local`), so never in production. It also refuses a
database that holds a lab neither it nor `seed_e2e` created. `--force` adds the data next
to such labs. It can run before or after `seed_e2e`.

## Check
```bash
tools/install-hooks.sh   # once per clone: secrets + ./check.sh, commit message and branch name checks
./check.sh               # secrets, migrations, API contract, lint, types, tests
./check.sh e2e           # plus Playwright against the real API (backend running, seeded below)
./check.sh audit         # plus pip-audit and npm audit (network)
```
The e2e tests sign in as `e2e-user`, who manages the lab "E2E lab". Seed it the way CI does,
and again after a failed run (it resets what the tests change):
```bash
docker compose exec -e E2E_PASSWORD='e2e correct horse battery' backend python manage.py seed_e2e
```

Role walkthroughs (on demand, not part of `./check.sh`): each role's daily tasks performed in
the browser and measured (steps, page loads, requests, time), against the data of `seed_dev`.
The table per role lands in `frontend/test-results/walkthroughs/summary.md`. Findings:
`docs/walkthroughs/`.
```bash
cd frontend && DEV_PASSWORD='dev correct horse battery' npm run walkthroughs
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

### Database roles (once per database)
The app never connects as the owner of its tables (ADR 0005). As a superuser, or the
database owner with CREATEROLE, create the roles and their privileges, then set the
two login passwords:
```bash
DATABASE_URL=postgres://<admin>@<host>/<db> python manage.py db_roles
psql ... -c '\password cultures_migration' -c '\password cultures_app'
```
`cultures_audit` (NOLOGIN) owns the audit tables and trigger functions,
`cultures_migration` runs migrations and owns the other tables, `cultures_app` is what
the app connects as: no TRUNCATE, ALTER or TRIGGER anywhere, only SELECT and INSERT on
the audit events, only SELECT on the row changes. Other names: `DB_AUDIT_OWNER_ROLE`,
`DB_MIGRATION_ROLE`, `DB_RUNTIME_ROLE` (set them for every step below). Run `db_roles`
again after `backend/cultures/audit/roles.py` changes. It is idempotent.

### Deploy steps, in order
1. With the new image and the real production environment of the app:
   `python manage.py check --deploy --fail-level WARNING`.
2. As the migration role, with a lock timeout so a long query cannot queue traffic
   behind a migration:
   `PGOPTIONS='-c lock_timeout=5s' DB_APPLICATION_NAME=cultures-migrate DATABASE_URL=<cultures_migration> python manage.py migrate`,
   then `python manage.py createcachetable` the same way. The end of `migrate` prints
   "Database roles: audit objects owned by cultures_audit ...": it gives new audit
   tables and functions to the audit owner and resets the app's grants. If it prints
   "privileges unchanged", migrate ran as the wrong role.
3. Start the new image with `DATABASE_URL=<cultures_app>`. `/readyz` answers 503 with
   `runtime_role` while the app connects as a role that owns a table or may TRUNCATE
   one (`DB_RUNTIME_ROLE_REQUIRED`, on by default in production).

Probes: `/healthz` (liveness, no dependencies) and `/readyz` (database, cache, no
unapplied migrations, the runtime role; 503 lists the failing checks). Both answer any
Host header, so a probe can use the pod IP.

### Audit reconciliation (scheduled)
Once a day, as `cultures_app` (it only reads):
`python manage.py audit_reconcile --since 25h`. It prints row changes that no service
event explains (a write from psql, a script or a forgotten `QuerySet.update()`) and
exits 1 when there is one. Alert on the exit code. Changes next to a system actor's
event, such as a data migration in `migration_audit()`, are printed as `known` and do
not fail it. Examples: cron `17 6 * * * ... audit_reconcile --since 25h || alert`, a
systemd timer, or a Kubernetes CronJob with the image and the app's environment.

### Login limits
Failed logins are counted per account and address, per address and per account
(ADR 0007, `backend/cultures/users/login_limits.py`). No account is ever locked for
everyone: while an account is under attack, a browser that signed in to it before still
may. Every failure and refusal logs a `login_failed` line (account reference, address
bucket, `surface` api or admin, `outcome`, request id), never the typed name, and an
account going under attack is an audit event. The user admin shows an account's
"Failed logins", and staff end the wait with "Clear login limits" and a reason (an
audit event). Once an hour, as `cultures_app`:
`python manage.py prune_login_failures` deletes ended counters, so a flood of made-up
names does not stay in the table.

Required environment: `DJANGO_SECRET_KEY` (or `DJANGO_SECRET_KEY_FILE`), `DATABASE_URL`
(or `DATABASE_URL_FILE`, the runtime role for the app), `DJANGO_ALLOWED_HOSTS`, `DJANGO_ADMIN_PATH` (not the default).
Behind a TLS proxy: `DJANGO_BEHIND_TLS_PROXY=true` and `DJANGO_TRUSTED_PROXIES`, the
proxies' addresses or networks, comma separated (`10.0.0.5` or `10.0.0.0/24`). The app
reads `X-Forwarded-For` only on a request that comes from one of them, from the right,
up to the first address not in the list; gunicorn takes the same list as
`forwarded_allow_ips`. Each proxy must append the address it saw (nginx
`proxy_add_x_forwarded_for`, plain addresses without ports): a hop that is not an
address ends the walk at the last trusted one. `DJANGO_NUM_PROXIES` and `GUNICORN_FORWARDED_ALLOW_IPS` are gone, and startup refuses
them. Optional: `DJANGO_SECRET_KEY_FALLBACKS` (key rotation), `LOG_FORMAT=json`,
`ERROR_REPORTING_DSN` (add `sentry-sdk` first), `DB_RUNTIME_ROLE_REQUIRED=false` (only
where the host gives the app no second role), `THROTTLE_*`, `LOGIN_PAIR_*`,
`LOGIN_ADDRESS_*`, `LOGIN_ACCOUNT_*` (`backend/config/settings/base.py`),
`DATA_UPLOAD_MAX_MEMORY_SIZE`. Startup refuses unsafe values; `./check.sh` runs
`check --deploy` with production settings.

The proxy must cap the request body (`client_max_body_size`): Django limits form
and JSON bodies but not the total size of uploaded files.

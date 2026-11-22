# Runbook

For the operator of the production stack in `deploy/` (README "One host: deploy/"). All
commands run from the checkout on the host, `/srv/culture-collection` below. Times are UTC.

## Start, stop, upgrade, rollback

| What | How |
|---|---|
| Start, or deploy a release | `deploy/deploy.sh X.Y.Z`: verifies the signatures, backs up, migrates, starts the API, the proxy and the scheduler, waits until all three are healthy |
| Upgrade | the same command with the new version. A release that does not come up healthy is replaced by the one before it, and the command names the step that failed |
| Roll back by hand | `deploy/deploy.sh <previous version>` (`deploy/state/previous` names it). Images only: a bad migration is undone by a restore of the backup taken before it ("Restore" below) |
| Stop | `docker compose -f deploy/compose.yaml stop`. The data stays in the `db-data` volume |
| Start again after a stop or a reboot | the containers restart by themselves (`restart: unless-stopped`); after a `down`, `deploy/deploy.sh <current version>` |
| State | `docker compose -f deploy/compose.yaml ps` (all four healthy), `logs --tail 100 <service>` |

Never `docker compose down -v`: `-v` deletes the database volume. Only the restore steps below
use it, after a backup.

## Backups (#177)

**What.** The database, which is all the data: the uploaded documents live in it.
`deploy/backup.sh` writes one set per backup into a restic repository: the roles
(`pg_dumpall --roles-only`), the dump (`pg_dump`, custom format) and a manifest with the
release and the row counts of the main tables. All three come from one database snapshot. The
manifest is written last, so a set without one is incomplete and is never restored. restic
encrypts everything with `secrets/restic_password`.

**Where.** `RESTIC_REPOSITORY` in `deploy/.env`: off the host and in the EU (ADR 0009), for
example `s3:https://<endpoint>/<bucket>/cultures` or `sftp:backup@<host>:/srv/cultures`.
Credentials for it go in `deploy/secrets/restic_env`, one `NAME=value` per line
(`AWS_ACCESS_KEY_ID=...`, `AWS_SECRET_ACCESS_KEY=...`), never on a command line.

**The restic password goes off the host too**, kept apart from the repository: in the
institution's password safe, or printed and locked away. Without it no backup can be read, and
losing the host is what a backup must survive. The same goes for `deploy/secrets/` as a whole.

**When.**

| What | When | How |
|---|---|---|
| `deploy/backup.sh run` | daily, at night | the timer below; it also applies the retention |
| `deploy/backup.sh before-migrate` | every deploy | `deploy/deploy.sh` runs it; a failed backup stops the deploy before migrate |
| `deploy/backup.sh check` | daily, after the backup | fails when the repository is damaged or the newest set is older than 26 h |
| a restore drill | every quarter | "Restore" below, into a stack of its own, result in the log book |

**Retention.** After each scheduled run: 14 daily, 8 weekly, 12 monthly sets
(`restic forget --prune`). Sets taken before a migrate count like any other.

**First time.** `deploy/deploy.sh secrets` writes `restic_password`. Then
`deploy/backup.sh init` creates the repository.

### Schedule

The backups run on the host, not in the scheduler service: they need docker, and no container
gets the docker socket (that would be root on the host). They report to Healthchecks through
the same `backend/tools/run_job.py` as the other jobs, with the host's `python3` (standard
library only). A systemd timer, as the deploying user, with `loginctl enable-linger` so it
runs while nobody is logged in, `~/.config/systemd/user/cultures-backup.service`:

```ini
[Unit]
Description=culture-collection backup and check

[Service]
Type=oneshot
Environment=HEALTHCHECKS_PING_URL_FILE=/srv/culture-collection/deploy/secrets/healthchecks_ping_url
ExecStart=/usr/bin/python3 /srv/culture-collection/backend/tools/run_job.py backup --timeout 7200 -- /srv/culture-collection/deploy/backup.sh run
ExecStart=/usr/bin/python3 /srv/culture-collection/backend/tools/run_job.py backup-check --timeout 1800 -- /srv/culture-collection/deploy/backup.sh check
```

and `cultures-backup.timer`:

```ini
[Unit]
Description=culture-collection backup, nightly

[Timer]
OnCalendar=*-*-* 02:30
Persistent=true
RandomizedDelaySec=10m

[Install]
WantedBy=timers.target
```

`systemctl --user enable --now cultures-backup.timer`. The checks `backup` and `backup-check`
alert when a run fails or does not come ("Scheduled jobs and alerts" below). With cron instead:

```cron
30 2 * * * cd /srv/culture-collection && HEALTHCHECKS_PING_URL_FILE=deploy/secrets/healthchecks_ping_url python3 backend/tools/run_job.py backup --timeout 7200 -- deploy/backup.sh run && HEALTHCHECKS_PING_URL_FILE=deploy/secrets/healthchecks_ping_url python3 backend/tools/run_job.py backup-check --timeout 1800 -- deploy/backup.sh check
```

### Restore

Who: the operator, with a manager of the lab told before and after (a restore can bring back
an older state of the records). Every restore and drill is written in the log book: when, which
set, why, the result of the verification.

1. `deploy/backup.sh restore latest` (or a set name, `deploy/backup.sh restore 20261120T023000Z`)
   restores into a stack of its own, the compose project `cultures-restore`, and verifies it:
   the row counts and the document digest must equal the manifest, and
   `manage.py audit_chain_verify` must find both audit chains intact. It refuses a project that
   has tables already, so it never writes over the running stack.
2. When the restored stack is to replace the running one: take a backup of the running one
   first (`deploy/backup.sh run`), stop it and remove its database
   (`docker compose -f deploy/compose.yaml down -v`), then restore into it:
   `deploy/backup.sh restore <set> --into cultures`, then `deploy/deploy.sh <release>` with the
   release the set names (`release` in the manifest, `restic dump` shows it). Remove the
   drill stack: `COMPOSE_PROJECT_NAME=cultures-restore docker compose -f deploy/compose.yaml down -v`.
3. `deploy/backup.sh verify <set> --into <project>` checks a restored stack again without
   restoring.

`deploy/e2e-restore.sh` runs all of this against a local repository, and CI runs it on every
pull request: a backup, a restore into an empty stack, the verification, and three refusals (a
restore over data, a row missing, an audit event edited).

## Scheduled jobs and alerts (#180)

The `scheduler` service runs `backend/crontab` with supercronic, from the API's image and as
the runtime role, so a release or a rollback moves it with the API. Every job goes through
`backend/tools/run_job.py`, which pings Healthchecks: `start`, then success, or the exit code
with the last 10 kB of the output, credentials taken out. Healthchecks emails when a job fails,
and when its ping does not come in time: that also catches a stopped scheduler or a host that
is down. `deploy/e2e-jobs.sh` runs every line of the crontab against a stand-in, in CI too.

**Setting it up.** A Healthchecks project of its own, on an instance in the EU (Healthchecks is
open source: healthchecks.io's EU hosting, or one the institution runs), with email
notifications to the operator and a second person. Its ping URL with the project's ping key,
`https://<instance>/ping/<ping-key>`, goes in `deploy/secrets/healthchecks_ping_url` (one
line; empty means nothing is reported, and each job says so once in its log). Then create one
check per row, with the slug, period and grace given here:

| Check (slug) | Runs | Period | Grace | Where |
|---|---|---|---|---|
| `heartbeat` | every 5 min | 5 min | 10 min | scheduler |
| `prune-login-failures` | hourly, :07 | 1 h | 30 min | scheduler |
| `clearsessions` | daily 03:17 | 1 day | 2 h | scheduler |
| `audit-reconcile` | daily 04:17 | 1 day | 2 h | scheduler |
| `audit-chain-anchor` | daily 04:47 | 1 day | 2 h | scheduler |
| `backup` | daily 02:30 | 1 day | 3 h | host timer |
| `backup-check` | daily, after the backup | 1 day | 3 h | host timer |

A ping that cannot reach Healthchecks never changes a job's result: the missing ping is the
alarm. Application errors (an exception in a request or a job) go to `ERROR_REPORTING_DSN` in
`deploy/.env`, a Sentry or GlitchTip project in the EU; empty means none are sent. Events carry
no personal data (`cultures/core/error_reporting.py`).

### When an alert comes

First for all of them: `docker compose -f deploy/compose.yaml ps` and the failed ping's body in
Healthchecks, which holds the end of the job's output. Then:

| Alert | What it means | First steps |
|---|---|---|
| `heartbeat` down | the API is not ready, the proxy does not serve the app, or the scheduler or the host is down | `ps`: which service is not healthy. `logs --tail 100 backend` (a failing `/readyz` names its check: `database`, `cache`, `migrations`, `runtime_role`). Host unreachable: the hosting provider |
| `heartbeat` fails, body names a URL | that URL did not answer 2xx | `runtime_role`: the API runs as an owner, redeploy with `deploy.sh`. `migrations`: a deploy stopped halfway, run it again. The proxy URL: `logs proxy`, the certificate |
| `audit-reconcile` fails | a row changed that no service event explains: a write from psql, a script, a bug | Do not "fix" the rows. The body lists the changes. Find who wrote them (time, role, request id), write it in the log book, tell a manager. ADR 0005 |
| `audit-chain-anchor` fails with "unanchored" | no qualified timestamp today: no authority configured, or it did not answer | Every day until `AUDIT_TIMESTAMP_BACKEND` names a provider (ADR 0009): a known gap, keep the check paused until then. With a provider: its status, then run the job again, `docker compose -f deploy/compose.yaml exec scheduler python manage.py audit_chain_anchor` |
| `prune-login-failures` or `clearsessions` fails | a database problem, usually | `logs scheduler`, then `heartbeat`. Harmless for a day: the tables only grow |
| `backup` fails or is late | no backup tonight | The body names the step. Repository unreachable or credentials: `deploy/secrets/restic_env`. Run it again by hand, `deploy/backup.sh run`, and watch `backup-check` |
| `backup-check` fails | the repository is damaged, or the newest set is older than 26 h | `deploy/backup.sh check` by hand. A damaged repository: start a new one and take a backup now, keep the old one until the next drill |
| an error report | an exception in the app | The event's request id: the same id is in the logs and in the audit trail of that request |

## A new user (#176)

Staff create the account (Django admin, Users) and a manager adds it to the lab. The manager
then opens the lab page, "Enrolment code" on the person's row, writes a reason and hands the
code over in person or by a call to a known number: it is shown once, valid for 24 hours
(ENROLMENT_CODE_HOURS) and for one enrolment. The person signs in with their password, types
the code and adds a security key or an authenticator app, then keeps the ten recovery codes.
A code that expired or was used: the manager issues a new one. A person in no lab (staff) gets
the code from a superuser, through `cultures.users.factors.enrolment_code_issue` with no lab in
`manage.py shell`, in an audit context.

## A lost second factor (#176)

A person who lost their security key and their phone signs in with a recovery code, then adds a
new factor on "Sign-in and security" (account menu). A person who also lost the recovery codes
asks two managers of their lab: one proposes a reset on the lab page ("Second factor resets"),
with a reason, the other one checks who is asking (in person, or a call to a known number) and
confirms with a reason. The person's keys, app and codes are gone, every session of theirs
ends, and the confirmer sees an enrolment code, once, to hand over at once: with it and the
password the person adds a new factor. A person in no lab (staff)
needs two superusers: the reset service, `cultures.users.factors.factor_reset_propose` with no
lab, from `manage.py shell` in an audit context. Each step is an audit event with its reason.

## Rotating secrets

Each in a quiet hour, with a backup first (`deploy/backup.sh run`), and written in the log book.
compose mounts each secret file as it was when the container was created, and `up -d` does not
recreate a container when only a file's content changed: every rotation ends with
`docker compose -f deploy/compose.yaml up -d --force-recreate --wait backend scheduler`
("recreate" below).

- **Django secret key** (`deploy/secrets/django_secret_key`): put the old key in `deploy/.env` as
  `DJANGO_SECRET_KEY_FALLBACKS=<old key>`, write a new random one into the file
  (`head -c 48 /dev/urandom | base64 | tr -d '/+=\n'`), recreate.
  Sessions and signed values stay valid through the fallback. After the session age (8 h,
  `SESSION_COOKIE_AGE`) remove the fallback and recreate again.
- **Database role passwords** (`db_migration_password`, `db_runtime_password`): write the new
  password into the file, and for the runtime role the same password into `database_url`, then
  `deploy/deploy.sh <current version>`, which sets the role passwords, then recreate, so the API
  and the scheduler connect with them. The admin password (`db_admin_password`) is set when the volume is
  created: change it with `ALTER ROLE cultures PASSWORD ...` in psql first, then the file.
- **restic password**: restic keeps several keys. Add the new one, then remove the old one, with
  the restic image of `deploy/backup.sh` (`RESTIC_IMAGE`) and the repository's credentials:
  `restic key add`, `restic key list`, `restic key remove <old id>`. Then write the new password
  into `deploy/secrets/restic_password` and **its copy off the host**: an old copy no longer
  opens the repository.
- **MFA secret key** (`deploy/secrets/mfa_secret_key`, #176): it encrypts the TOTP secrets of
  the authenticator apps. A new key makes every app unreadable, so do not rotate it without a
  reason: the people sign in with their security key or a recovery code, then add the app
  again. Keep its copy off the host with the others.
- **Healthchecks ping key**: rotate it in the project's settings, write the new URL into
  `deploy/secrets/healthchecks_ping_url`, recreate (the host timer reads the file at each run).
- **TLS certificate**: renewed outside the stack, then `docker compose -f deploy/compose.yaml
  exec proxy nginx -s reload`.

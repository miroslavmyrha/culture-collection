# Runbook

For the operator of the production stack in `deploy/` (README "One host: deploy/"). Scheduled
jobs and alerts other than the backup are #180.

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

A systemd timer (as the deploying user, with `loginctl enable-linger` so it runs while nobody
is logged in), `~/.config/systemd/user/cultures-backup.service`:

```ini
[Unit]
Description=culture-collection backup and check

[Service]
Type=oneshot
ExecStart=/srv/culture-collection/deploy/backup.sh run
ExecStart=/srv/culture-collection/deploy/backup.sh check
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

`systemctl --user enable --now cultures-backup.timer`. A failed run is a failed unit:
`systemctl --user --failed`, and an alert on it belongs to #180. With cron instead:

```cron
30 2 * * * /srv/culture-collection/deploy/backup.sh run && /srv/culture-collection/deploy/backup.sh check || <alert command>
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

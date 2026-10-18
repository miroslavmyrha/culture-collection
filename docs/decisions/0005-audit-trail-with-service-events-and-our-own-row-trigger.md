# 0005 Audit trail with service events and our own row trigger

Date: 2026-10-17
Status: accepted (after the spike in issue #8). Roles, claims and reconciliation built in #34.
Amended 2026-10-18: personal data and erasure (#37).
Deciders: maintainer

## Context

Every change to collection data must say who, when, what and why, and must
survive writes that skip `save()`: `QuerySet.update()`, `bulk_create`, raw
SQL, data migrations and psql sessions. Audit rows must never change. This is
hard to change after the first domain migration (#9 onward).

Considered (facts as of 2026-10-17, PyPI and GitHub):
- django-pghistory 3.9.2: triggers through django-pgtrigger, the closest
  fit. No commit in 90 days, Django 6.1 not declared, three bugs without an
  answer that hit us (#261 context with psycopg 3, #258 executemany, #202
  `values()` aliasing). django-pgtrigger 4.17.0 has no Django 6.1 support
  yet (PR #227 open since 2026-10-09).
- django-simple-history 3.13.0, django-auditlog 3.4.1: signals, so they miss
  `QuerySet.update()`, bulk paths and raw SQL. Django 6.1 not declared.
- pgaudit: statement text in the server log, no row values, best effort and
  not transactional (its README). Good for DDL and role changes only.
- Trigger designs we read for ideas, no code taken: supa_audit (Apache-2.0),
  the 2ndQuadrant audit-trigger 91plus (PostgreSQL License), pgMemento
  (LGPL-3.0), and the PostgreSQL 18 docs (CREATE TRIGGER, "Writing SECURITY
  DEFINER Functions Safely"). Research notes on PG 18.6: an unset setting
  reads as `''` after the first local `set_config` in a session, and TRUNCATE
  fires no row trigger.
- Own code: about 900 lines of Python and SQL including comments, every
  path tested and proven by mutations.

## Decision

Use no audit library. Two layers in `cultures.audit`:
1. **Service events** (`AuditEvent`): a service runs in `audited_atomic()`
   and calls `record_event()` or `record_batch()` in the same transaction.
   Event types come from a registry, the actor and request id from the audit
   context (the request, or `audit_context()` in commands, tasks and
   `migration_audit()` in data migrations). No context raises.
2. **Row backstop** (`RowChange`): our own PL/pgSQL triggers on every
   regulated table, attached in the table's migration with
   `attach_row_audit()`. They store a logical table label, the pk as text,
   only changed columns for UPDATE, never the excluded columns, the actor and
   request id from `set_config`, the txid, the login role and
   `application_name`. A statement trigger records TRUNCATE. Secret columns
   (the password hash) are never stored either, but an UPDATE that changes
   one records the column with the marker `"redacted"` (update of
   2026-10-17 below).

Both tables are append-only: model guards, triggers that refuse UPDATE,
DELETE and TRUNCATE (TRUNCATE only for non-owners, so Django's test flush
works), and production grants.

## Migration impact

Additive: two tables, four functions, triggers on `users_user`. Reversible
(`migrate audit zero` drops all of it, users first). Each regulated table
adds one migration with `attach_row_audit()`. Changing exclusions is
detach plus attach in a migration. Adding a reason-required event type
changes a check constraint: on a large table write it NOT VALID, then
VALIDATE. #9 adds the tenant column to `AuditEvent`. #34 adds
`RowChange.actor_claim_invalid` (a constant default, metadata only) and
replaces both trigger function bodies (0008). The roles are no migration:
they come from `manage.py db_roles`. #37 replaces `audit_row_change()` again
(0010), re-attaches the users triggers with personal columns (users 0006) and
adds `users_user.erased_at` with a check constraint (users 0007; the CHECK
scans the users table once, which is small).

## Consequences

+ `update()`, bulk paths, raw SQL, COPY and psql are captured. A RowChange
  with a null actor, or a txid with no AuditEvent, is a change no service
  explains.
+ The app role cannot forge or edit audit rows (SECURITY DEFINER, grants).
- Measured on the dev stack (Intel N100, PostgreSQL 18.6, median of 5):
  bulk_create of 10 000 users 1.4 s with the triggers, 0.59 s without
  (2.4x); one `update()` of 10 000 users 1.3 s against 0.15 s (about 8x); 1 000
  single-row updates 0.8 s against 0.5 s (1.5x). The research run measured
  about 6x for bulk INSERT and 13x for bulk UPDATE of 100 000 rows on
  PG 18. Statement triggers with transition tables are the escape hatch for
  import-heavy tables (about 3x and 8x there, slower for single rows).
- Bypasses by privileged roles: `ALTER TABLE ... DISABLE TRIGGER`,
  `session_replication_role = replica`, dropping the triggers, TRUNCATE by
  the owner, also as a cascade (`TRUNCATE users_user CASCADE` as the owner
  empties `audit_auditevent`). So production runs the app as a role that
  owns nothing (see Roles). pgaudit logs DDL and ROLE statements, so a
  disabled trigger is seen. A data-only `pg_restore` fires the triggers
  unless `--disable-triggers` is given.
- RowChange `actor_id` and `request_id` are claims, not proof: any session
  can `set_config('app.actor_id', ...)`, so psql can name another user (see
  Claims). They join the two layers and point at who to ask. The service
  event's actor, written by the app from the authenticated request, is the
  record of who acted.
- Our code to maintain. `operations.py` and `migration_audit()` are imported
  by migrations, so their output must never change (new shapes get new
  functions).
- Unpartitioned. If volume needs it: monthly range partitions on
  `occurred_at`, archived with DETACH PARTITION, never DELETE.

## Update 2026-10-17: secret columns (#33)

The first version dropped excluded columns from every row, and an UPDATE
that changed only excluded columns wrote no row. So a password change by an
admin, a shell (`set_password()` and `save()`) or `changepassword` left no
trace in either table. Now:
- `RowAudit.secret` lists secret columns, passed to the trigger as
  `secret:<column>` after the plain exclusions. Audit migration 0006 replaces
  `audit_row_change()` (CREATE OR REPLACE, same owner, grants and triggers):
  INSERT and DELETE rows still leave a secret out, and an UPDATE that changes
  it stores `{"<column>": "redacted"}` in old and new, next to the other
  changed columns. Plain exclusions (`last_login`) behave as before.
- Users migration 0003 re-attaches the users triggers with `password` as a
  secret. The tables attached before pass no secret argument, so their rows
  do not change.
- The services record the meaning: `user_password_changed` (whether a usable
  password exists, never a value), and user creation, profile, staff,
  superuser and active changes as their own events, the privilege ones with a
  required reason. Django admin, `createsuperuser`, `changepassword` and
  `seed_e2e` go through them.

Any later change to `audit_row_change()` (for example validating the
settings it reads) must start from the 0006 body, or the marker is lost:
`audit/tests/test_row_changes.py` fails when it is.

## Roles (#34)

Built in `cultures/audit/roles.py`, the single source for the setup and the
tests:
- `cultures_audit`, NOLOGIN, owns the audit tables and every `audit_*`
  function, so the SECURITY DEFINER trigger writes `audit_rowchange` as this
  role and nobody else needs INSERT on it.
- `cultures_migration` runs `migrate` and `createcachetable` and owns every
  other table. It is a member of the audit owner, so migrations can still
  change the audit tables, and the TRUNCATE guard lets it through. It is as
  privileged as the owner and is used only by the deploy job.
- `cultures_app`, the runtime role, owns nothing, is a member of no role and
  has exactly `APP_ROLE_GRANTS`: SELECT and INSERT on `audit_auditevent`,
  SELECT on `audit_rowchange` and `django_migrations`, SELECT, INSERT, UPDATE
  and DELETE on every other table. No TRUNCATE, TRIGGER, REFERENCES or
  MAINTAIN, and no sequence privileges (identity columns need none). It
  cannot empty, alter, unhook or forge the audit trail, also not through a
  cascade.

`manage.py db_roles`, run once by an admin and again when `roles.py`
changes, creates the roles, moves the tables to their owners, declares the
default privileges of the migration role (so `createcachetable` and new
tables reach the runtime role) and applies the grants. It is idempotent.
After every `migrate` run as the migration role, a `post_migrate` handler
hands audit tables and functions that a migration created back to the audit
owner and resets the runtime privileges to `APP_ROLE_GRANTS`. A migrate under
another role (development) changes nothing and says so in its output. With
`DB_RUNTIME_ROLE_REQUIRED` (on in production) `/readyz` fails while the app
connects as a role that owns a table or may TRUNCATE one, and CI runs the e2e
suite with the runtime role (`tools/up-with-runtime-role.sh`).

Names come from `DB_AUDIT_OWNER_ROLE`, `DB_MIGRATION_ROLE` and
`DB_RUNTIME_ROLE`. Passwords are set by the admin with psql `\password`.

## Claims (#34)

Migration 0008 (after #33's 0006, from its body, so the secret marker
stays) makes the trigger read the settings as claims that never
block a write: `app.actor_id` is kept only when it is 1 to 19 ASCII digits
within the bigint range, otherwise `actor_id` is null and
`actor_claim_invalid` is true. `app.request_id` is cut to 64 characters.
Before, a value like `not-a-number` made every regulated write in that
session fail. `audit_context(request_id=...)` refuses an id that is not 1 to
64 letters, digits or hyphens, the format of `X-Request-ID`.

## Reconciliation (#34)

`manage.py audit_reconcile --since 25h` reports row changes no service
explains and exits 1 when it finds one: `no_event` (no AuditEvent in the
same txid), `invalid_actor`, and `no_actor` (null actor while every event of
that transaction names a user). A null actor next to an event of a system
actor (a command, a task, a data migration in `migration_audit()` with
channel `migration`) is printed as `known` with that event's channel and
label and does not fail the run. The lookup is `NOT EXISTS` on the indexed
`txid`, an anti join. Schedule it daily with an hour of overlap, as the
runtime role (it only reads), and alert on a non-zero exit (README, Deploy).

Fallback: if the triggers cost too much on a table, switch that table to
statement triggers with transition tables. If our code proves wrong,
django-pghistory once it supports Django 6.1 and fixes #261, keeping
`AuditEvent` as the meaning layer.

Revisit when: a table needs more than about 1 000 audited writes a second,
django-pgtrigger ships Django 6.1 support and pghistory answers #261, or a
regulator asks for a format we cannot produce from these two tables.

## Update 2026-10-18: personal data and erasure (#37)

Before this update the trail copied people into rows that never change: the
row trigger stored usernames, names and emails in `RowChange`, the
`user_created` and `user_changed` events held them in `changes`, and
`actor_label` was the actor's username. An erasure could not reach any of
them without breaking append-only. The policy now:

- **No personal value enters an append-only row.**
  - Row trigger: `RowAudit.personal` is a fourth class next to audited,
    excluded and secret, passed to the trigger as `personal:<column>` after
    the secrets. Audit migration 0010 (from the 0008 body, so the claims and
    the secret marker stay) stores the marker `"personal"` instead of the
    value in INSERT, UPDATE and DELETE rows, so a row still shows that the
    column was there or changed. `users_user.username`, `first_name`,
    `last_name` and `email` are personal (users migration 0006). The
    classification invariant covers all four classes and fails for a column
    in no class or in two, and for a registry entry that names a table or a
    column that does not exist.
  - The other regulated tables: `labs_lab.name` and `code` name an
    organisational unit, not a person, and stay audited so old labels remain
    traceable. Labs are named after their field or unit; a lab named after a
    person keeps that name in its history. `labs_membership` holds ids and a
    role only. `users_user` ids, flags, `date_joined` and `erased_at` stay
    audited: they describe the account, not who it is.
  - Service events: a personal field of the subject is recorded as
    `{field: "changed"}` (`registry.PERSONAL_FIELDS`). The services pass it
    so, and `record_event()` and `record_batch()` replace any value a service
    passes by mistake. Other fields keep `[old, new]`; nothing reads
    `schema_version` yet, so it stays 1.
  - Actor label: `user:<public_id>` for a user, the existing labels
    (`command:...`, `migration:...`, `login-limits`) for system
    actors. A screen that shows the actor renders it through the `actor` FK
    at read time. Today that is Django admin's object history (it reads the
    user row, so an erased actor shows as `erased-<public_id>`).
    `audit_reconcile` prints the labels as stored: its output goes to logs,
    which no erasure reaches, so it keeps the pseudonym.
  - No data migration writes events or row changes yet, so none holds a
    personal value.
- **Free text names nobody.** `reason` and any later note field are stored
  for good. The admin's reason fields say so in their help text. A reason
  says why ("erasure request 2026-114"), never who.
- **Erasure is the tombstone.** `user_erase(user=..., reason=...)` (event
  `user_erased`, reason required) overwrites the user row in place: username
  `erased-<public_id>`, empty names and email, an unusable password,
  inactive, not staff, not superuser, `erased_at` set. The pk, `public_id`
  and `date_joined` stay, so every PROTECT foreign key and every audit row
  still resolves. In the same transaction it removes the memberships through
  `membership_delete` (one `member_removed` event each), deletes the user's
  sessions and login counters, and renames the user in Django's admin log,
  which copies `str(user)` into `object_repr`. It locks the user row with
  every active superuser's row (by pk), then the labs by pk, then the
  memberships. It refuses with `last_manager` when the user is a lab's last
  active manager (also for an inactive manager of a lab without an active
  one, as `membership_delete` does for everybody) and with `last_superuser`
  for the last active superuser, and then changes nothing. A second erasure
  is a no-op without an event, like every service that finds nothing to
  change. An erased user cannot sign in, and every other user service
  refuses it with `user_erased`, `user_activate` included. A check
  constraint (`users_user_erased_is_a_tombstone`) holds the tombstone
  against any writer. Usernames starting with `erased-` are reserved, so a
  live account cannot take the name an erasure needs. The admin has an
  "Erase user" page (the username typed again and a reason); an erased user
  is read-only there.
- **No scrub migration.** No production database holds real people yet, so
  rows written before 0010 are not rewritten. If one ever does, the scrub is
  a one-time data migration run as the migration role: inside its own
  transaction it lifts the append-only trigger of the audit tables, replaces
  personal values in old `RowChange` and `AuditEvent` rows with the markers,
  sets a `scrubbed` flag and records one `audit_scrubbed` event with the
  count. It is the only write an audit row may ever see, and it is audited.

Proven by a test that gives one person a marker in every personal field,
renames them twice, lets them act through a command, the API and the admin,
erases them through the admin page, and then searches every text, varchar,
char and json(b) column of every table for the marker: zero hits, and
`audit_reconcile` reports no alarm.

Revisit when: a new table holds a person (classify its columns as
personal), a note or comment field arrives (free text), or the first
production database with real people exists before a change of this policy
(then the scrub above is required).

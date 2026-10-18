# 0005 Audit trail with service events and our own row trigger

Date: 2026-10-17
Status: accepted (after the spike in issue #8)
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
VALIDATE. #9 adds the tenant column to `AuditEvent`.

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
  the owner. So production runs the app as a role that owns nothing: a
  NOLOGIN `audit_owner` owns the audit tables and functions, the migration
  role creates the schema, the runtime role gets SELECT and INSERT on
  `audit_auditevent`, only SELECT on `audit_rowchange`, and no TRUNCATE on
  regulated tables. pgaudit logs DDL and ROLE statements, so a disabled
  trigger is seen. A data-only `pg_restore` fires the triggers unless
  `--disable-triggers` is given.
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

Fallback: if the triggers cost too much on a table, switch that table to
statement triggers with transition tables. If our code proves wrong,
django-pghistory once it supports Django 6.1 and fixes #261, keeping
`AuditEvent` as the meaning layer.

Revisit when: a table needs more than about 1 000 audited writes a second,
django-pgtrigger ships Django 6.1 support and pghistory answers #261, or a
regulator asks for a format we cannot produce from these two tables.

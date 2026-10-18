# 0006 Scope every record by lab with four ordered roles per membership

Date: 2026-10-17
Status: accepted
Deciders: maintainer

## Context

Every later record (strains, deposits, vials, storage, distribution) belongs
to one lab, and a person can work in several labs with different rights. The
shape of the role model is in every query and every permission test from #9
on, and the `lab` column goes into every later table, so changing it later
means migrating all of them.

Considered (facts as of 2026-10-17, PyPI and GitHub through library-health):
- Django groups and model permissions: global, so "curator in lab A, viewer
  in lab B" needs a group per lab and role, and nothing scopes the rows.
- django-guardian 3.5.1: object permission rows per user and object. Active
  (released 2026-10-16), Django 6.1 not declared. One row per object and
  permission grows with the data; listing "everything I may see" needs joins
  on its tables for every query. It answers "may I do X to this object", not
  "which labs am I in".
- rules 3.5: predicates in code, no rows. Last release 2024-09, no commit in
  90 days, Django 6.1 not declared. The predicate part is about twenty lines
  of our own.
- Own code: `Membership(user, lab, role)` unique per user and lab, roles
  mapped to permissions in `cultures/labs/permissions.py`, one access object
  per request (`{lab_id: role}`, `labs_with(perm)`), the pattern of the
  production apps in django-patterns (`security-and-audit.md`, Access and
  scope). About 80 lines.

Also decided with it (by the maintainer): labs are created only by staff in
Django admin, the API reads them; lab managers add, change and remove
members; no superuser or staff shortcut in the API.

## Decision

Use per-lab memberships with four ordered roles, viewer < technician <
curator < manager, each holding the permissions of the roles below it plus
its own (`GRANTS` in `permissions.py`). Every model with a `lab` foreign key
uses `LabScopedQuerySet` (`for_access(access, perm)`), enforced by an
invariant test over the app registry. Managers grant at most their own role,
a lab never loses its last active manager (amended below), and every change
is an audited service call (ADR 0005). `AuditEvent` gets the `lab` tenant
column ADR 0005 promised.

## Migration impact

Additive: `labs_lab`, `labs_membership` (row-audited), a nullable
`audit_auditevent.lab_id` and a concurrently built index on it. Reversible
while no later table points at labs. After #10 every new table carries
`lab_id`, so replacing the model then means a data migration per table.

## Consequences

+ One question answers every read: `labs_with(perm)`. List and detail use
  the same scope, 404 outside it, 403 for a missing role.
+ Later features add permissions to `GRANTS` instead of their own checks.
- A role is one value per lab: no "curator for strains, viewer for storage".
  That needs a permission set per membership.
- The grant ceiling cannot trigger today (only managers manage members and
  nothing is above them). It is tested with a patched role map so it holds
  the day a lower role manages members.
- Staff need a membership to use the API like anybody else; admin is their
  tool. Staff access to lab data through the API (with a reason and an
  expiry) is not built.

## Amendment 2026-10-18: an active manager (#35)

"A lab never loses its last manager" counted inactive users. A deactivated
user keeps the membership, so a lab could end with only inactive managers,
and then nobody manages its members through the API. Deactivating the last
manager had the same effect. Decided:
- Only active managers count, everywhere the rule is checked: the services,
  the admin lab form, and user deactivation.
- Deactivating a user who is the last active manager of a lab is refused
  (`LastManager`, code `last_manager`, the message names the lab). Staff make
  another member a manager first, then deactivate. `users_deactivate` is all
  or nothing: one such user refuses the whole batch.
- No forced deactivation with a reason. Forcing it would create the state
  the rule exists to prevent, and the way out (name a successor) is one
  admin save. Considered and rejected: a `force` flag with a reason, and a
  `replacement` argument on `user_deactivate`, which mixes a membership
  change into a user service.
- A refused attempt changes nothing and records nothing, like every other
  refusal: the service's transaction rolls back with its event and row
  changes. The audit trail records what happened, not what was tried.
- Lock order: user rows (by pk), then lab rows (by pk), then memberships.
  Deactivation locks the users, then every lab they belong to (any role, so
  a concurrent promotion waits too), and reads the managers under those
  locks. `membership_create` locks the new member's user row, so no
  membership appears for a user while the user is being deactivated. The
  grantor's role and active flag are re-read under the lab lock, so a
  grantor deactivated after the request built its access object is refused.
- A lab that already has no active manager stays editable in admin, so staff
  can name one.

Known limits: the admin lab form is the one place that locks a lab before a
user: `lab_update` runs before the inline adds members. If the API adds the
same user to the same lab at that moment, PostgreSQL detects the deadlock
and aborts one of the two, which would have failed as a duplicate anyway. Changing a membership or a user with
`QuerySet.update()` or SQL skips the rule (the row trigger still records
it), as for every other rule in the services.

Fallback: if per-object exceptions appear (a strain shared with one external
person), add object grants next to the lab role, not instead of it.

Revisit when: a lab needs a fifth role or split rights within a role, records
must be shared between labs, or a membership needs an expiry.

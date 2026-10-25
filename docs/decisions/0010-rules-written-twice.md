# 0010 Rules written twice in Python and the database

Date: 2026-10-25
Status: proposed (#122)
Deciders: maintainer

## Context

The services decide every rule and give the user a reason. The database refuses what must never
be stored, whoever writes it: a bug, the admin, a script, raw SQL (ADR 0005, ADR 0009). So a rule
that guards regulated data or the history lives on both sides.

Both sides are written by hand. No trigger is generated from Python. Only Django
`CheckConstraint`s built from shared constants (`BASES`, `ROOT_KINDS`, `METHODS_BY_KIND`, the
`MAX_*` limits, `DUAL_USE_ENTRY`, `PARTIAL_DATE`, `COUNTRY_CODES`) come from one source, and
`makemigrations --check` in `check.sh` keeps them in step.

A survey on 2026-10-25 (develop ff7a565) found 27 rules written twice. Three are proven to agree
by a test that tries every pair against both the trigger and the Python constant: vial edges
(`lineage/tests/test_vial_states.py`), batch edges (`test_batch_states.py`) and request edges
(`distribution/tests/test_request_states.py`). The storage kind spec has an every-pair test
against the trigger, and the service reads the same constant. The rest are tested by examples.

Drift in one direction fails closed: Python allows something new, the trigger refuses, a test
goes red. Drift in the other direction is the danger: Python gets stricter, the database keeps
the old rule, every test stays green, and a write outside the services does what the app refuses.
Live cases:

- "Not in a box" statuses: `NOT_IN_A_BOX` (`lineage/models.py:216`), a literal in
  `lineage_vial_guard` and again in `lineage_placement_guard` (lineage 0004), a fourth copy in
  `test_constraints.py`. Adding a status to the constant changes nothing in the database.
- "Regulated": `regulating_restrictions()` (`strains/selectors.py:15`) is the one Python
  definition, `distribution_shipment_guard` (distribution 0008) restates it as
  `ended_at IS NULL`. Widening it in Python asks for two people in the app; a one-step shipment
  by SQL still passes.
- Package facts: `PACKAGE_FIELDS` (`distribution/models.py`) and the column list the shipment
  guard compares. A new field is compared in Python only.
- Documents a shipment needs: `REGISTERED` (`distribution/documents.py:78`) and two triggers in
  distribution 0010 that name the kinds by hand.
- Event types that need a reason: `reason_required_codes()` (`audit/registry.py`) and a literal
  list in the live constraint (audit 0022, `SeparateDatabaseAndState`). `makemigrations --check`
  compares the state, not the database.
- Risk group 4: refused by the service, allowed by `strains_strain_risk_group_1_to_4`. By design
  today, written nowhere as a decision.

Other Python-only rules write regulated data with no database guard at all: `may_store` at
placement, the approval gates, "only released distribution stock leaves", lineage coherence
(same strain, passage number), `Strain.taxon` equal to the current identification.

## Decision

1. **Python is the one source of each rule.** A constant or a function names it: an edge table,
   a set of statuses, a predicate. The service uses it. Nothing else defines the rule.

2. **The database keeps its guard where a wrong row is a legal or historical fault**: regulated
   strains, distribution, lineage, audit, frozen rows. Defence in depth stays (ADR 0005, 0009).
   Elsewhere the service alone is enough, and no new trigger is added.

3. **Single-row rules become Django constraints built from the constant**, so
   `makemigrations --check` fails when the constant changes without a migration. A trigger is
   for what a constraint cannot say: transitions (OLD to NEW), other rows, frozen rows.

4. **Migrations stay frozen.** A trigger body in a migration is a literal, never built from a live
   constant at import time: an old migration must produce the same database forever. When the
   constant changes, a new migration replaces the function, as today.

5. **Every twin has a parity test against the live database, generated from the Python source.**
   For a set or an edge table: every member and every non-member, every pair, tried on the
   trigger, the way the three edge tests do it. For a predicate over rows ("regulated"): the
   test builds each case the predicate distinguishes and asserts the trigger agrees. A change
   to the constant without a migration fails a test, in either direction.

6. **A registry names each twin**: `cultures/<app>/rules.py` lists the rule, its Python source,
   the trigger or constraint, and the parity test. An invariant test fails when a trigger in the
   database (read from `pg_trigger`) is in no registry entry and not marked as a frozen-row or
   infrastructure guard, and when an entry names a test that does not exist.

7. **A rule that is stricter in Python on purpose says so** in its registry entry with the
   reason, written by the maintainer (risk group 4 is the first such entry; its reason is an
   open question below). Without that note the parity test treats a difference as a failure.

## Follow-up, by risk

One issue each, in this order. Each adds the parity test first (it must fail where the sides
differ today), then aligns the database.

1. "Regulated" in the shipment guard, and the package fields it compares.
2. Event types that need a reason: the live constraint from `reason_required_codes()`.
3. "Not in a box": one Python set, both triggers replaced, the test copy removed.
4. Documents a shipment needs: the trigger kinds from `REGISTERED`.
5. Deposit status edges: an edge table in Python (none exists, `_locked_deposit(expected)` holds
   them implicitly) and an every-pair test; today 4 pairs are sampled.
6. The registry and its invariant test, filled with the 27 twins.
7. Decide, one at a time, which Python-only regulated rules get a database guard: `may_store` at
   placement and "only released distribution stock leaves" first.

Small fixes found on the way: `lineage/models.py:186` and `:306` say "migration 0005", the
triggers are in 0004; `distribution/migrations/0003_guards.py:10` says 16 request edges, there
are 36.

## Consequences

- A rule change is one constant plus one migration, and a test fails until both are in.
- The dangerous drift (Python stricter, database weaker) becomes a red test instead of a quiet
  gap.
- More tests, each exhaustive over a small set: seconds, not minutes.
- The registry is one more file per app to keep; the invariant test keeps it honest.

## Alternatives considered

- **The database as the one source**: the service writes and maps the database error to a
  domain error. Rejected: the user gets the reason late, in the trigger's words, after locks;
  rules that need several reads (gates, `may_store`) do not fit a trigger.
- **Python only, drop the triggers**: rejected for regulated data and history (ADR 0005, 0009).
  The admin, scripts and bugs write too.
- **Generate trigger bodies from Python after migrate** (`post_migrate`, as the migration role
  already does for grants): one true source, but the SQL leaves the migration history, review
  sees no diff of the trigger, and a rollback has nothing to go back to. Kept as an option if
  the parity tests prove too costly.
- **Keep the status quo with example tests**: rejected, the survey found live gaps of the
  dangerous kind.

## Open questions

- Risk group 4: the service refuses it, the database accepts it. Keep the database looser on
  purpose (and say why), or make the constraint 1 to 3.
- Which Python-only regulated rules get a database guard (follow-up 7), and whether the cost of
  a guard on `may_store`, which reads the whole storage path, is worth it.

## Sources

- Survey of 2026-10-25 on develop ff7a565: every `RunSQL` migration read, latest live function
  definitions, Python sources and tests, file and line for each of the 27 twins.
- Existing every-pair tests: `lineage/tests/test_vial_states.py`,
  `lineage/tests/test_batch_states.py`, `distribution/tests/test_request_states.py`,
  `storage/tests/test_tree.py`.

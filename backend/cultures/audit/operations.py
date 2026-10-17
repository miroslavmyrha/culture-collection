"""Migration operations that attach the row audit triggers to a table, or detach them.

A regulated table's own migration attaches them, with the same values as its
entry in registry.ROW_AUDITED_TABLES:

    from cultures.audit.operations import attach_row_audit

    class Migration(migrations.Migration):
        dependencies = [("audit", "0003_row_change_function"), ("strains", "0001_initial")]
        operations = [attach_row_audit("strains_strain", label="strains.strain")]

Changing the exclusions later is a migration with detach_row_audit (old
values) and attach_row_audit (new values): explicit and reviewed.

Migrations import this module, so its output is part of every migration that
already ran: never change what these functions emit. A new trigger shape gets
new functions and a new migration per table.

Three triggers per table:
- audit_row_change: AFTER INSERT OR DELETE, FOR EACH ROW;
- audit_row_update: AFTER UPDATE, FOR EACH ROW, WHEN (OLD IS DISTINCT FROM NEW),
  so a save() that changes nothing never calls the function. Record comparison
  needs an equality operator for every column: jsonb has one, json does not;
- audit_row_truncate: AFTER TRUNCATE, FOR EACH STATEMENT (row triggers never
  see TRUNCATE).
"""

import json
import re

from django.db import migrations

ROW_TRIGGERS = ("audit_row_change", "audit_row_update", "audit_row_truncate")
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_LABEL = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")


def _checked(pattern: re.Pattern[str], name: str) -> str:
    """Only plain lower-case names: they are spliced into SQL as identifiers and literals."""
    if not pattern.fullmatch(name):
        raise ValueError(f"not a plain SQL name: {name!r}")
    return name


def row_trigger_args(label: str, pk: tuple[str, ...], exclude: tuple[str, ...]) -> tuple[str, ...]:
    """The arguments of the row triggers: label, pk columns as a JSON array, exclusions."""
    for column in (*pk, *exclude):
        _checked(_IDENTIFIER, column)
    return (_checked(_LABEL, label), json.dumps(list(pk)), *exclude)


def _create(table: str, label: str, pk: tuple[str, ...], exclude: tuple[str, ...]) -> str:
    table = _checked(_IDENTIFIER, table)
    args = ", ".join(f"'{arg}'" for arg in row_trigger_args(label, pk, exclude))
    return f"""
CREATE TRIGGER audit_row_change AFTER INSERT OR DELETE ON {table}
    FOR EACH ROW EXECUTE FUNCTION audit_row_change({args});
CREATE TRIGGER audit_row_update AFTER UPDATE ON {table}
    FOR EACH ROW WHEN (OLD IS DISTINCT FROM NEW) EXECUTE FUNCTION audit_row_change({args});
CREATE TRIGGER audit_row_truncate AFTER TRUNCATE ON {table}
    FOR EACH STATEMENT EXECUTE FUNCTION audit_row_truncate('{label}');
"""


def _drop(table: str) -> str:
    table = _checked(_IDENTIFIER, table)
    return "".join(f"DROP TRIGGER {name} ON {table};\n" for name in ROW_TRIGGERS)


def attach_row_audit(
    table: str, *, label: str, pk: tuple[str, ...] = ("id",), exclude: tuple[str, ...] = ()
) -> migrations.RunSQL:
    """Every INSERT, UPDATE, DELETE and TRUNCATE on `table` writes RowChange rows."""
    return migrations.RunSQL(_create(table, label, pk, exclude), _drop(table))


def detach_row_audit(
    table: str, *, label: str, pk: tuple[str, ...] = ("id",), exclude: tuple[str, ...] = ()
) -> migrations.RunSQL:
    """The reverse of attach_row_audit; the same arguments, so the reverse can re-attach."""
    return migrations.RunSQL(_drop(table), _create(table, label, pk, exclude))

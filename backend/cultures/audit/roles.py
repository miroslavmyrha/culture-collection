"""The database roles of ADR 0005 and what each may do. This module is the single source.

Three roles, named in settings.DATABASE_ROLES:
- audit owner (NOLOGIN): owns the audit tables and every audit_* function. The
  SECURITY DEFINER row trigger runs as this role, so audit_rowchange is written
  only through the trigger.
- migration role: runs migrate and createcachetable and owns every other table.
  It is a member of the audit owner, so a migration can still change an audit
  table or function, and the TRUNCATE guard lets it through like the owner.
- runtime role: what the app connects as. It owns nothing, is a member of no
  role and has exactly APP_ROLE_GRANTS. No TRUNCATE, TRIGGER, REFERENCES or
  MAINTAIN anywhere, so it can neither empty the audit tables (also not through
  a cascade from a regulated table) nor disable or drop a trigger.

setup() runs once per database as an admin (`manage.py db_roles`) and again
whenever this file changes: it is idempotent. apply_grants() runs after every
migrate as the migration role (post_migrate, apps.py): it hands audit tables
and functions that a migration created to the audit owner and resets the
runtime role's table privileges to APP_ROLE_GRANTS. Tables created outside
migrate (createcachetable) get the runtime privileges from the default
privileges that setup() declares for the migration role.

Identity columns need no sequence privilege (an INSERT as a role with only
table grants takes its id, checked on PostgreSQL 18.6), so the runtime role
gets none.
"""

import re
from dataclasses import dataclass, fields

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.backends.utils import CursorWrapper

_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_FUNCTION = re.compile(r"^audit_[a-z0-9_]*\([a-z0-9_, ]*\)$")

# What the runtime role may do on a table: DOMAIN_TABLE unless the table is listed here.
DOMAIN_TABLE: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE", "DELETE")
APP_ROLE_GRANTS: dict[str, tuple[str, ...]] = {
    # Append-only: services insert events, nothing updates, deletes or truncates them.
    "audit_auditevent": ("SELECT", "INSERT"),
    # Written only by the SECURITY DEFINER trigger as the audit owner, never by the app.
    "audit_rowchange": ("SELECT",),
    # The readiness probe reads it, only migrate writes it.
    "django_migrations": ("SELECT",),
    # Login counters (cultures.users.login_limits): the upsert inserts, updates and returns
    # the count, a success, a staff clear and prune_login_failures delete. Not row-audited.
    "users_loginfailures": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    # Taxa are never deleted: strains and identifications point at them (PROTECT), and a
    # name that is wrong becomes a synonym or is corrected. External ids may be removed.
    "taxonomy_taxon": ("SELECT", "INSERT", "UPDATE"),
    # Permits are ended with a date and a reason, never deleted (ADR 0009).
    "biosafety_labauthorisation": ("SELECT", "INSERT", "UPDATE"),
    # Strains and their history are never deleted: numbers are never reused (ADR 0008, D2),
    # identifications and restrictions are history. A trigger refuses deletes too.
    "strains_strain": ("SELECT", "INSERT", "UPDATE"),
    # #79: a medium is added, renamed and retired, never deleted (its trigger refuses it too).
    "growth_growthmedium": ("SELECT", "INSERT", "UPDATE"),
    "strains_straincounter": ("SELECT", "INSERT", "UPDATE"),
    "strains_strainidentification": ("SELECT", "INSERT", "UPDATE"),
    "strains_strainrestriction": ("SELECT", "INSERT", "UPDATE"),
    # #105: a proposal to end a restriction is confirmed or withdrawn once, never deleted (its
    # trigger).
    "strains_restrictionendproposal": ("SELECT", "INSERT", "UPDATE"),
    # #20: a proposal to deaccession a strain is confirmed or withdrawn once, never deleted (its
    # trigger).
    "strains_straindeaccessionproposal": ("SELECT", "INSERT", "UPDATE"),
    # Depositors, deposits, terms, MTA versions and passages are never deleted (#10, #12):
    # a contact is erased in place, the rest is history. Guard triggers refuse deletes too.
    "deposits_contact": ("SELECT", "INSERT", "UPDATE"),
    "deposits_depositor": ("SELECT", "INSERT", "UPDATE"),
    # Frozen rows: inserted, never updated (a trigger refuses it as well).
    "deposits_mtatemplate": ("SELECT", "INSERT"),
    "deposits_deposit": ("SELECT", "INSERT", "UPDATE"),
    "deposits_depositterms": ("SELECT", "INSERT", "UPDATE"),
    "deposits_termsuse": ("SELECT", "INSERT"),
    "lineage_passage": ("SELECT", "INSERT"),
    # #16: batches change their status, vials their status and barcode, a placement gets its
    # one removal. None is ever deleted (triggers refuse it as well).
    "lineage_batch": ("SELECT", "INSERT", "UPDATE"),
    "lineage_vial": ("SELECT", "INSERT", "UPDATE"),
    "lineage_vialplacement": ("SELECT", "INSERT", "UPDATE"),
    # #17: a check is only added, and its one change is being entered in error (a trigger).
    "lineage_batchcheck": ("SELECT", "INSERT", "UPDATE"),
    # #18: nothing of distribution is ever deleted (triggers refuse it as well). Requesters and
    # the counter change; a permit is ended once; a request changes its status; a reservation
    # ends once. Documents, lines, the permits a line was approved against and acceptances are
    # only added (frozen by triggers).
    "distribution_requester": ("SELECT", "INSERT", "UPDATE"),
    "distribution_document": ("SELECT", "INSERT"),
    "distribution_recipientpermit": ("SELECT", "INSERT", "UPDATE"),
    "distribution_distributionrequest": ("SELECT", "INSERT", "UPDATE"),
    "distribution_requestcounter": ("SELECT", "INSERT", "UPDATE"),
    "distribution_requestline": ("SELECT", "INSERT"),
    "distribution_linepermit": ("SELECT", "INSERT"),
    "distribution_mtaacceptance": ("SELECT", "INSERT"),
    "distribution_vialreservation": ("SELECT", "INSERT", "UPDATE"),
    # #88: a shipment and its vials are only added (frozen by triggers).
    "distribution_shipment": ("SELECT", "INSERT"),
    "distribution_shipmentvial": ("SELECT", "INSERT"),
    # #89: a prepared shipment is withdrawn once, never deleted (its trigger).
    "distribution_shipmentpreparation": ("SELECT", "INSERT", "UPDATE"),
    # #90: a shipment's documents are kept as sent (the trigger refuses UPDATE and DELETE too).
    "distribution_shipmentdocument": ("SELECT", "INSERT"),
    # ADR 0009: a location grant is revoked, never deleted.
    "labs_locationgrant": ("SELECT", "INSERT", "UPDATE"),
    # Storage units are retired, never deleted: events and, from #16, placements point at
    # them. Box types are referenced by boxes. A trigger refuses deletes too.
    "storage_boxtype": ("SELECT", "INSERT", "UPDATE"),
    "storage_storageunit": ("SELECT", "INSERT", "UPDATE"),
}


def runtime_privileges(table: str) -> tuple[str, ...]:
    return APP_ROLE_GRANTS.get(table, DOMAIN_TABLE)


def audit_tables() -> list[str]:
    """The audit app's tables. Each needs an explicit APP_ROLE_GRANTS entry."""
    tables = sorted(model._meta.db_table for model in apps.get_app_config("audit").get_models())
    missing = [table for table in tables if table not in APP_ROLE_GRANTS]
    if missing:
        raise ImproperlyConfigured(
            f"audit tables without an APP_ROLE_GRANTS entry in cultures/audit/roles.py: {missing}"
        )
    return tables


@dataclass(frozen=True)
class Roles:
    audit_owner: str
    migration: str
    runtime: str

    def __post_init__(self) -> None:
        names = [getattr(self, field.name) for field in fields(self)]
        for name in names:
            if not _ROLE_NAME.fullmatch(name):  # spliced into SQL as identifiers
                raise ImproperlyConfigured(f"not a plain role name: {name!r}")
        if len(set(names)) != len(names):
            raise ImproperlyConfigured(f"the three database roles must differ: {names}")


def configured_roles() -> Roles:
    return Roles(**settings.DATABASE_ROLES)


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _tables(cursor: CursorWrapper) -> dict[str, str]:
    """Every table of the public schema with its owner."""
    cursor.execute(
        "SELECT c.relname, pg_get_userbyid(c.relowner) FROM pg_class c"
        " WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')"
    )
    return dict(cursor.fetchall())


def _refuse_privileged_roles(cursor: CursorWrapper, roles: Roles) -> None:
    cursor.execute(
        "SELECT rolname FROM pg_roles r WHERE rolname = %s AND (rolsuper OR rolcreaterole"
        " OR rolcreatedb OR rolreplication OR rolbypassrls"
        " OR EXISTS (SELECT FROM pg_auth_members a WHERE a.member = r.oid))"
        " UNION ALL SELECT rolname FROM pg_roles WHERE rolname = %s AND rolcanlogin",
        [roles.runtime, roles.audit_owner],
    )
    refused = [name for (name,) in cursor.fetchall()]
    if refused:
        raise ImproperlyConfigured(
            f"refusing to set up {refused}: the runtime role must be a plain login role that is"
            " a member of no role, and the audit owner must be NOLOGIN"
        )


def setup(cursor: CursorWrapper, roles: Roles) -> None:
    """Create the roles if missing, then make privileges and owners what ADR 0005 says.

    Runs as a superuser, or as the database owner with CREATEROLE that is a member
    of the roles it creates. Login passwords are not set here (psql \\password).
    """
    for name, login in (
        (roles.audit_owner, "NOLOGIN"),
        (roles.migration, "LOGIN"),
        (roles.runtime, "LOGIN"),
    ):
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [name])
        if cursor.fetchone() is None:
            cursor.execute(f"CREATE ROLE {name} {login}")
    _refuse_privileged_roles(cursor, roles)
    cursor.execute(f"GRANT {roles.audit_owner} TO {roles.migration}")
    cursor.execute(
        f"GRANT USAGE, CREATE ON SCHEMA public TO {roles.migration}, {roles.audit_owner}"
    )
    cursor.execute(f"GRANT USAGE ON SCHEMA public TO {roles.runtime}")
    cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")  # the PostgreSQL 15+ default
    cursor.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {roles.migration} IN SCHEMA public"
        f" GRANT {', '.join(DOMAIN_TABLE)} ON TABLES TO {roles.runtime}"
    )
    # A database that ran as one owner so far: the migration role takes its tables.
    audit = set(audit_tables())
    for table, owner in _tables(cursor).items():
        if table not in audit and owner != roles.migration:
            cursor.execute(f"ALTER TABLE public.{_quoted(table)} OWNER TO {roles.migration}")
    apply_grants(cursor, roles)


def apply_grants(cursor: CursorWrapper, roles: Roles) -> None:
    """Audit objects to the audit owner, runtime privileges exactly APP_ROLE_GRANTS.

    Idempotent. Runs as the migration role after every migrate, or inside setup().
    """
    tables = _tables(cursor)
    for table in audit_tables():
        if table in tables and tables[table] != roles.audit_owner:
            cursor.execute(f"ALTER TABLE public.{_quoted(table)} OWNER TO {roles.audit_owner}")
    cursor.execute(
        "SELECT p.oid::regprocedure::text FROM pg_proc p"
        " WHERE p.pronamespace = 'public'::regnamespace AND p.proname LIKE 'audit\\_%%'"
        " AND pg_get_userbyid(p.proowner) <> %s",
        [roles.audit_owner],
    )
    for (function,) in cursor.fetchall():
        if not _FUNCTION.fullmatch(function):
            raise ImproperlyConfigured(f"unexpected audit function signature: {function!r}")
        cursor.execute(f"ALTER FUNCTION public.{function} OWNER TO {roles.audit_owner}")
    tables = _tables(cursor)
    owners = (roles.migration, roles.audit_owner)
    foreign = sorted(table for table, owner in tables.items() if owner not in owners)
    if foreign:
        raise ImproperlyConfigured(
            f"tables not owned by {roles.migration} or {roles.audit_owner}: {foreign}."
            " Run manage.py db_roles as an admin."
        )
    cursor.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {roles.runtime}")
    cursor.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {roles.runtime}")
    for table in sorted(tables):
        privileges = ", ".join(runtime_privileges(table))
        cursor.execute(f"GRANT {privileges} ON public.{_quoted(table)} TO {roles.runtime}")

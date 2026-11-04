"""Create the database roles of ADR 0005 and give them their privileges. Idempotent.

    DATABASE_URL=<an admin> python manage.py db_roles

Run it once per database as a superuser, or as the database owner with
CREATEROLE that is a member of the roles it creates, and again after
cultures/audit/roles.py changes. It creates the three roles if they are
missing (names from DB_AUDIT_OWNER_ROLE, DB_MIGRATION_ROLE, DB_RUNTIME_ROLE),
hands every table to the migration role and the audit tables and functions to
the audit owner, declares the default privileges for tables the migration role
creates later, and grants the runtime role exactly APP_ROLE_GRANTS. Passwords
are set separately (psql \\password), so they never pass through a command line.

It runs before the first migrate (ADR 0005's deploy order,
tools/up-with-runtime-role.sh), so on a fresh database most audit tables and all
audit functions do not exist yet: it owns and grants what is there and demands
nothing. What the migrations create is owned and granted by `migrate` itself,
whose own run of apply_grants then requires every function the app may call
(cultures/audit/roles.py). So after a deploy that changes roles.py, run this
command and then migrate, in that order.
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from cultures.audit.roles import configured_roles, setup


class Command(BaseCommand):
    help = "Create the ADR 0005 database roles and apply their privileges (as an admin)."

    def handle(self, *args: Any, **options: Any) -> None:
        roles = configured_roles()
        with transaction.atomic(), connection.cursor() as cursor:
            setup(cursor, roles)
        self.stdout.write(
            f"Database roles ready: {roles.audit_owner} (audit owner), {roles.migration}"
            f" (migrations), {roles.runtime} (the app)."
            " Set the login passwords with psql \\password."
        )

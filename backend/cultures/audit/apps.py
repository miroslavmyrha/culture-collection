import sys
from typing import IO, Any

from django.apps import AppConfig
from django.db import connections, transaction
from django.db.models.signals import post_migrate


def apply_database_roles(
    *, using: str, verbosity: int = 1, stdout: IO[str] | None = None, **kwargs: Any
) -> None:
    """After every migrate as the migration role: audit objects owned by the audit owner,
    runtime privileges exactly APP_ROLE_GRANTS (cultures/audit/roles.py).

    Connected as any other role (development and tests run as the owner) it changes
    nothing and says so, so a migrate that ran as the wrong role is visible in its output.
    """
    from .roles import apply_grants, configured_roles  # noqa: PLC0415 (apps are not ready at import)

    roles = configured_roles()
    out = stdout or sys.stdout
    with transaction.atomic(using=using), connections[using].cursor() as cursor:
        cursor.execute("SELECT current_user")
        row = cursor.fetchone()
        user = row[0] if row else None
        if user != roles.migration:
            if verbosity >= 1:
                out.write(
                    f"Database roles: connected as {user}, not {roles.migration}:"
                    " privileges unchanged.\n"
                )
            return
        apply_grants(cursor, roles)
    if verbosity >= 1:
        out.write(
            f"Database roles: audit objects owned by {roles.audit_owner},"
            f" {roles.runtime} has the privileges of APP_ROLE_GRANTS.\n"
        )


def _on_post_migrate(sender: AppConfig, **kwargs: Any) -> None:
    apply_database_roles(**kwargs)


class AuditConfig(AppConfig):
    name = "cultures.audit"
    label = "audit"

    def ready(self) -> None:
        # Once per migrate: post_migrate is sent for every app, this receiver listens to one.
        post_migrate.connect(_on_post_migrate, sender=self, dispatch_uid="audit.database_roles")

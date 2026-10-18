"""users_user: username, first_name, last_name and email become personal columns of the row audit.

From now on the trigger stores the marker "personal" for them in every row
(audit migration 0010), never their values, so no name or email enters
audit_rowchange (#37). The password stays a secret and last_login a plain
exclusion. The values are those of audit.registry.ROW_AUDITED_TABLES["users_user"].
Rows written before this migration keep their values: no production database
held real people before it (ADR 0005, update of 2026-10-18).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit, detach_row_audit


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0005_login_failures"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        detach_row_audit(
            "users_user", label="users.user", exclude=("last_login",), secret=("password",)
        ),
        attach_row_audit(
            "users_user",
            label="users.user",
            exclude=("last_login",),
            secret=("password",),
            personal=("username", "first_name", "last_name", "email"),
        ),
    ]

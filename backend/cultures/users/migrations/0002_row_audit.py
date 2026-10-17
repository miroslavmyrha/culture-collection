"""Row audit on users_user, with the values of audit.registry.ROW_AUDITED_TABLES["users_user"].

password and last_login are never stored: one is a secret, the other changes on
every login.
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
        ("audit", "0003_row_change_function"),
    ]

    operations = [
        attach_row_audit("users_user", label="users.user", exclude=("password", "last_login"))
    ]

"""users_user: the password becomes a secret column of the row audit.

Its value is still never stored, but a change of it now writes an UPDATE row
with a marker (audit migration 0006), so every password change leaves a trace.
last_login stays a plain exclusion: it changes on every login. The values are
those of audit.registry.ROW_AUDITED_TABLES["users_user"].
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit, detach_row_audit


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_row_audit"),
        ("audit", "0006_row_change_secret_marker"),
    ]

    operations = [
        detach_row_audit("users_user", label="users.user", exclude=("password", "last_login")),
        attach_row_audit(
            "users_user", label="users.user", exclude=("last_login",), secret=("password",)
        ),
    ]

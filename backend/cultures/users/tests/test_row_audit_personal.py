"""The row trigger stores the marker for personal user columns, never their values (#37).

Each personal column is changed through every write path: the service, the
admin form, QuerySet.update() and raw SQL. Each change must leave exactly one
UPDATE row with the marker as old and new value, and neither the old nor the
new value anywhere in audit_rowchange. A created and a deleted user carry the
marker for every personal column.
"""

from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection
from django.test import Client
from django.urls import reverse

from cultures.audit.context import audit_context, audited_atomic
from cultures.audit.models import Channel, RowChange
from cultures.audit.registry import PERSONAL_MARKER, ROW_AUDITED_TABLES, SECRET_MARKER
from cultures.users import services
from cultures.users.models import User

from .conftest import make_user
from .test_admin import form_of

pytestmark = pytest.mark.django_db

PERSONAL = ROW_AUDITED_TABLES["users_user"].personal
MARKED = dict.fromkeys(PERSONAL, PERSONAL_MARKER)


def value_for(field: str) -> str:
    """A value no fixture uses, valid for the field (usernames allow letters, digits, @.+-_)."""
    return "zz-personal@example.org" if field == "email" else f"zz-personal-{field}"


def by_service(staff: User, user: User, field: str, value: str) -> None:
    with audit_context(channel=Channel.COMMAND, actor=staff):
        services.user_update(user=user, changes={field: value})


def by_admin(staff: User, user: User, field: str, value: str) -> None:
    client = Client()
    client.force_login(staff)
    response = client.post(
        reverse("admin:users_user_change", args=[user.pk]), form_of(user, **{field: value})
    )
    assert response.status_code == 302, response.content


def by_queryset_update(staff: User, user: User, field: str, value: str) -> None:
    with audit_context(channel=Channel.COMMAND, actor=staff), audited_atomic():
        User.objects.filter(pk=user.pk).update(**{field: value})


def by_raw_sql(staff: User, user: User, field: str, value: str) -> None:
    assert field in PERSONAL  # a known column name, spliced as an identifier
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE users_user SET {field} = %s WHERE id = %s", [value, user.pk])  # noqa: S608


PATHS: dict[str, Callable[[User, User, str, str], None]] = {
    "service": by_service,
    "admin": by_admin,
    "queryset_update": by_queryset_update,
    "raw_sql": by_raw_sql,
}


def stored_text() -> str:
    """Every old and new value of every row change, as one text."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT string_agg(coalesce(old::text, '') || coalesce(new::text, ''), ' ')"
            " FROM audit_rowchange"
        )
        ((text,),) = cursor.fetchall()
    return str(text or "")


def user_rows(user: User, op: str) -> list[Any]:
    return list(
        RowChange.objects.filter(table_label="users.user", row_pk=str(user.pk), op=op).order_by(
            "pk"
        )
    )


@pytest.mark.parametrize("path", sorted(PATHS))
@pytest.mark.parametrize("field", PERSONAL)
def test_a_personal_change_leaves_one_row_with_the_marker_and_no_value(
    field: str, path: str
) -> None:
    staff = make_user("staff", is_staff=True, is_superuser=True)
    user = make_user("member", first_name="Ada", last_name="Lovelace")
    old = getattr(user, field)
    value = value_for(field)

    PATHS[path](staff, user, field, value)

    user.refresh_from_db()
    assert getattr(user, field) == value  # the change itself happened
    (row,) = user_rows(user, "UPDATE")
    assert (row.old, row.new) == ({field: PERSONAL_MARKER}, {field: PERSONAL_MARKER})
    text = stored_text()
    assert value not in text
    assert old not in text


def test_create_and_delete_leave_the_marker_for_every_personal_column() -> None:
    with audit_context(channel=Channel.COMMAND, actor=make_user("staff")):
        user = services.user_create(
            username="zz-created",
            password=None,
            email="zz-created@example.org",
            first_name="Zelda",
            last_name="Zimmer",
        )
    pk = user.pk
    with connection.cursor() as cursor:  # users are never deleted by the app: psql would
        cursor.execute("DELETE FROM users_user WHERE id = %s", [pk])

    (insert,) = user_rows(user, "INSERT")
    (delete,) = user_rows(user, "DELETE")
    assert {k: insert.new[k] for k in PERSONAL} == MARKED
    assert {k: delete.old[k] for k in PERSONAL} == MARKED
    assert insert.new["id"] == delete.old["id"] == pk  # audited columns keep their values
    text = stored_text()
    assert [v for v in ("zz-created", "Zelda", "Zimmer") if v in text] == []


def test_an_empty_personal_column_is_marked_too() -> None:
    """The marker says the column was there, not that it held something."""
    user = make_user("plain", first_name="")
    (insert,) = user_rows(user, "INSERT")
    assert insert.new["first_name"] == PERSONAL_MARKER


def test_a_personal_write_that_changes_nothing_leaves_no_row() -> None:
    user = make_user("same", first_name="Ada")
    User.objects.filter(pk=user.pk).update(first_name="Ada", last_name=user.last_name)
    assert user_rows(user, "UPDATE") == []


def test_markers_join_the_other_changed_columns_and_only_the_changed_ones() -> None:
    user = make_user("mixed")
    user.set_password("a-new-secret-password")
    user.email = "zz-mixed@example.org"
    user.is_staff = True
    user.save()

    (row,) = user_rows(user, "UPDATE")
    assert row.old == {"password": SECRET_MARKER, "email": PERSONAL_MARKER, "is_staff": False}
    assert row.new == {"password": SECRET_MARKER, "email": PERSONAL_MARKER, "is_staff": True}

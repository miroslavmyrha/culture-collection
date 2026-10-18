"""The row triggers on users_user: the backstop for writes that skip the services."""

from collections.abc import Iterator
from typing import Any, cast

import pytest
from django.db import connection, transaction
from model_bakery import baker

from cultures.audit.context import AuditContext, audit_context, audited_atomic, migration_audit
from cultures.audit.models import AuditEvent, Channel, RowChange
from cultures.audit.operations import attach_row_audit
from cultures.audit.registry import PERSONAL_MARKER, SECRET_MARKER
from cultures.users.models import User
from cultures.users.services import user_deactivate, users_deactivate

from .conftest import make_user

pytestmark = pytest.mark.django_db

# Every users_user column the trigger stores, the personal ones as the marker only (#37);
# password and last_login never.
STORED = {
    "id",
    "username",
    "first_name",
    "last_name",
    "email",
    "is_staff",
    "is_active",
    "is_superuser",
    "date_joined",
    "public_id",
}


def rows(op: str, label: str = "users.user") -> list[Any]:
    """Typed Any: old and new are JSON (Any | None to mypy), the tests index into them."""
    return list(RowChange.objects.filter(table_label=label, op=op).order_by("pk"))


def execute(sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else []


@pytest.fixture
def in_audited_atomic(audited: AuditContext) -> Iterator[AuditContext]:
    with audited_atomic() as context:
        yield context


def test_bulk_create_gives_one_insert_row_per_user_with_actor_and_request_id(
    admin: User, in_audited_atomic: AuditContext
) -> None:
    created = User.objects.bulk_create(
        [User(username=f"bulk{i}", email=f"bulk{i}@example.org") for i in range(3)]
    )

    inserted = rows("INSERT")[1:]  # the first one is the admin fixture's
    assert [r.row_pk for r in inserted] == [str(u.pk) for u in created]
    assert {(r.actor_id, r.request_id, r.old) for r in inserted} == {(admin.pk, "cmd-1", None)}
    assert [r.new["username"] for r in inserted] == [PERSONAL_MARKER] * 3
    assert {frozenset(r.new) for r in inserted} == {frozenset(STORED)}
    assert {(r.db_role, r.db_application) for r in inserted} == {("cultures", "cultures")}


def test_queryset_update_gives_update_rows_with_only_the_changed_columns(
    admin: User, in_audited_atomic: AuditContext
) -> None:
    first, second = make_user("first"), make_user("second")

    User.objects.filter(pk__in=[first.pk, second.pk]).update(first_name="Ada", is_staff=False)

    updated = rows("UPDATE")
    assert [r.row_pk for r in updated] == [str(first.pk), str(second.pk)]
    assert {(r.actor_id, r.request_id) for r in updated} == {(admin.pk, "cmd-1")}
    # is_staff was already False: unchanged, so not stored
    marked = {"first_name": PERSONAL_MARKER}
    assert [(r.old, r.new) for r in updated] == [(marked, marked)] * 2


def test_a_raw_sql_update_is_captured(admin: User, in_audited_atomic: AuditContext) -> None:
    member = make_user("member")
    execute("UPDATE users_user SET email = 'new@example.org' WHERE id = %s", [member.pk])

    (row,) = rows("UPDATE")
    marked = {"email": PERSONAL_MARKER}
    assert (row.row_pk, row.old, row.new) == (str(member.pk), marked, marked)
    assert row.actor_id == admin.pk


def test_a_change_outside_audited_atomic_is_captured_with_no_actor(member: User) -> None:
    """Like a psql session: nothing called set_config, so the row is an alarm."""
    execute("UPDATE users_user SET is_staff = true WHERE id = %s", [member.pk])

    (row,) = rows("UPDATE")
    assert (row.actor_id, row.request_id) == (None, None)
    assert (row.old, row.new, row.db_role) == ({"is_staff": False}, {"is_staff": True}, "cultures")


def test_a_plain_update_after_a_service_write_succeeds_with_no_actor(
    admin: User, member: User
) -> None:
    """After set_config ran once, current_setting() returns '' and not null: NULLIF needed."""
    with audit_context(channel=Channel.COMMAND, actor=admin, reason="left the lab"):
        user_deactivate(user=member)
    other = make_user("other")

    User.objects.filter(pk=other.pk).update(first_name="Plain")

    row = RowChange.objects.get(op="UPDATE", row_pk=str(other.pk))
    assert (row.actor_id, row.request_id, row.new) == (None, None, {"first_name": PERSONAL_MARKER})


def test_a_save_that_changes_nothing_writes_no_row(member: User) -> None:
    member.save()
    User.objects.filter(pk=member.pk).update(first_name="")
    assert rows("UPDATE") == []


def test_a_password_change_outside_the_services_leaves_a_marker_without_the_hash(
    member: User,
) -> None:
    """set_password() and save() in a shell: the row says the password changed, not to what."""
    member.set_password("a-new-secret-password")
    member.save()

    stored: list[Any] = list(RowChange.objects.filter(row_pk=str(member.pk)).order_by("pk"))
    assert [(r.op, r.old, r.new, r.actor_id) for r in stored[1:]] == [
        ("UPDATE", {"password": SECRET_MARKER}, {"password": SECRET_MARKER}, None)
    ]
    assert (stored[0].op, set(stored[0].new)) == ("INSERT", STORED)  # INSERT: no password


def test_a_change_of_last_login_alone_writes_no_row(member: User) -> None:
    User.objects.filter(pk=member.pk).update(last_login="2026-10-17T10:00:00Z")

    stored: list[Any] = list(RowChange.objects.filter(row_pk=str(member.pk)))
    assert [r.op for r in stored] == ["INSERT"]


def test_a_secret_marker_joins_the_other_changed_columns(member: User) -> None:
    member.set_password("a-new-secret-password")
    member.first_name = "Renamed"
    member.save()

    (update,) = rows("UPDATE")
    marked = {"password": SECRET_MARKER, "first_name": PERSONAL_MARKER}
    assert (update.old, update.new) == (marked, marked)


def test_the_password_hash_appears_in_no_row_change(in_audited_atomic: AuditContext) -> None:
    user = User.objects.create_user("secretive", password="first-secret-password")
    first_hash = user.password
    user.set_password("second-secret-password")
    user.first_name = "Changed"
    user.save()
    second_hash = user.password
    row_pk = str(user.pk)
    user.delete()

    assert [r.op for r in RowChange.objects.filter(row_pk=row_pk).order_by("pk")] == [
        "INSERT",
        "UPDATE",
        "DELETE",
    ]
    stored_text = execute(
        "SELECT coalesce(old::text, '') || coalesce(new::text, '') FROM audit_rowchange"
    )
    leaked = [text for (text,) in stored_text if first_hash in text or second_hash in text]
    assert leaked == []


def test_a_delete_is_captured_with_the_old_values_without_excluded_columns(
    admin: User, in_audited_atomic: AuditContext
) -> None:
    member = make_user("leaving")
    member.set_password("another-secret-password")
    member.save()

    User.objects.filter(pk=member.pk).delete()

    (row,) = rows("DELETE")
    assert (row.row_pk, row.new, row.actor_id) == (str(member.pk), None, admin.pk)
    assert set(row.old) == STORED
    assert (row.old["username"], row.old["email"]) == (PERSONAL_MARKER, PERSONAL_MARKER)


def test_a_truncate_is_captured_once_per_table(
    admin: User, in_audited_atomic: AuditContext
) -> None:
    """TRUNCATE fires no row trigger; the statement trigger leaves one row without a pk."""
    execute("TRUNCATE users_user CASCADE")

    (row,) = rows("TRUNCATE")
    assert (row.row_pk, row.old, row.new) == (None, None, None)
    assert (row.actor_id, row.request_id) == (admin.pk, "cmd-1")


def test_service_events_and_row_changes_join_by_request_id_and_txid(
    audited: AuditContext,
) -> None:
    members = baker.make(User, _quantity=2)

    users_deactivate(users=members)

    events = AuditEvent.objects.filter(request_id="cmd-1")
    changed = RowChange.objects.filter(request_id="cmd-1")
    assert events.count() == 3
    assert changed.count() == 2
    assert set(changed.values_list("row_pk", flat=True)) == {str(m.pk) for m in members}
    assert set(changed.values_list("occurred_at", "txid")) == set(
        events.values_list("occurred_at", "txid")
    )


def test_two_statements_in_one_transaction_share_the_txid_not_the_stmt_at(
    member: User, in_audited_atomic: AuditContext
) -> None:
    User.objects.filter(pk=member.pk).update(first_name="One")
    User.objects.filter(pk=member.pk).update(first_name="Two")
    user_deactivate(user=member)

    updated = rows("UPDATE")
    assert len(updated) == 3
    assert len({r.stmt_at for r in updated}) == 3
    ((txid,),) = execute("SELECT pg_current_xact_id()::text::bigint")
    assert {r.txid for r in updated} == {txid}
    assert AuditEvent.objects.get().txid == txid


def test_a_nested_audited_atomic_restores_the_outer_settings(admin: User) -> None:
    other = make_user("other")
    with audit_context(channel=Channel.COMMAND, actor=admin, request_id="outer"), audited_atomic():
        with (
            audit_context(channel=Channel.TASK, actor=other, request_id="inner"),
            audited_atomic(),
        ):
            inner = make_user("in-inner")
        after = make_user("after-inner")

    assert list(
        RowChange.objects.filter(op="INSERT", row_pk__in=[str(inner.pk), str(after.pk)])
        .order_by("pk")
        .values_list("actor_id", "request_id")
    ) == [(other.pk, "inner"), (admin.pk, "outer")]


def test_a_nested_audited_atomic_that_rolls_back_leaves_the_outer_settings(admin: User) -> None:
    other = make_user("other")
    with audit_context(channel=Channel.COMMAND, actor=admin, request_id="outer"), audited_atomic():
        with (
            pytest.raises(ZeroDivisionError),
            audit_context(channel=Channel.TASK, actor=other, request_id="inner"),
            audited_atomic(),
        ):
            rolled_back = make_user("rolled-back")
            _ = 1 / 0
        after = make_user("after-rollback")

    assert list(
        RowChange.objects.filter(op="INSERT", row_pk__in=[str(rolled_back.pk), str(after.pk)])
        .order_by("pk")
        .values_list("row_pk", "actor_id", "request_id")
    ) == [(str(after.pk), admin.pk, "outer")]


def test_a_nested_audited_atomic_marked_for_rollback_leaves_the_outer_settings(
    admin: User,
) -> None:
    other = make_user("other")
    with audit_context(channel=Channel.COMMAND, actor=admin, request_id="outer"), audited_atomic():
        with audit_context(channel=Channel.TASK, actor=other), audited_atomic():
            marked = make_user("marked")
            transaction.set_rollback(True)
        after = make_user("after-mark")

    assert list(
        RowChange.objects.filter(
            op="INSERT", row_pk__in=[str(marked.pk), str(after.pk)]
        ).values_list("row_pk", "actor_id", "request_id")
    ) == [(str(after.pk), admin.pk, "outer")]


def test_a_data_migration_context_tags_its_changes(member: User) -> None:
    with migration_audit("0009_normalise_emails", reason="lower-case emails") as context:
        User.objects.filter(pk=member.pk).update(email="MEMBER@example.org")

    (row,) = rows("UPDATE")
    assert (row.actor_id, row.request_id) == (None, context.request_id)
    assert (context.channel, context.actor_label) == (
        "migration",
        "migration:0009_normalise_emails",
    )


def test_the_trigger_writes_the_real_table_even_when_a_temp_table_shadows_it(
    member: User,
) -> None:
    """search_path is pinned and the table schema-qualified: pg_temp cannot hijack it."""
    execute("CREATE TEMP TABLE audit_rowchange (LIKE public.audit_rowchange)")
    execute("UPDATE users_user SET first_name = 'Shadow' WHERE id = %s", [member.pk])

    assert execute("SELECT count(*) FROM pg_temp.audit_rowchange") == [(0,)]
    assert execute(
        "SELECT new FROM public.audit_rowchange WHERE op = 'UPDATE' AND row_pk = %s",
        [str(member.pk)],
    ) == [('{"first_name": "personal"}',)]


@pytest.mark.parametrize("function", ["audit_row_change", "audit_row_truncate"])
def test_the_trigger_functions_are_security_definer_with_a_pinned_search_path(
    function: str,
) -> None:
    assert execute("SELECT prosecdef, proconfig FROM pg_proc WHERE proname = %s", [function]) == [
        (True, ["search_path=pg_catalog, pg_temp"])
    ]


def test_a_composite_key_is_stored_as_a_json_array_and_a_rename_keeps_the_label() -> None:
    execute(
        "CREATE TABLE audit_test_pair (lab integer, code text, note text, PRIMARY KEY (lab, code))"
    )
    attach = attach_row_audit("audit_test_pair", label="audit.pair", pk=("lab", "code"))
    execute(cast(str, attach.sql))
    execute("INSERT INTO audit_test_pair VALUES (7, 'A-1', 'first')")
    execute("ALTER TABLE audit_test_pair RENAME TO audit_test_pair_renamed")
    execute("UPDATE audit_test_pair_renamed SET note = 'second'")

    assert [
        (r.op, r.row_pk) for r in [*rows("INSERT", "audit.pair"), *rows("UPDATE", "audit.pair")]
    ] == [
        ("INSERT", '[7, "A-1"]'),
        ("UPDATE", '[7, "A-1"]'),
    ]


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_the_settings_end_with_the_transaction(admin: User) -> None:
    """Transaction-local: the next transaction on the same connection has no actor."""
    with audit_context(channel=Channel.COMMAND, actor=admin, request_id="once"), audited_atomic():
        inside = make_user("inside")
    with transaction.atomic():
        after = make_user("after")

    assert list(
        RowChange.objects.filter(op="INSERT", row_pk__in=[str(inside.pk), str(after.pk)])
        .order_by("pk")
        .values_list("actor_id", "request_id")
    ) == [(admin.pk, "once"), (None, None)]

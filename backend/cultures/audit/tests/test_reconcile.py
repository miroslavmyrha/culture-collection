"""audit_reconcile: row changes that no service event explains (cultures/audit/reconcile.py).

The cases need writes in separate transactions, so they run with
transaction=True. Each test prepares its data first and then reads the
database clock: findings are asked for since that moment, because the flush
after an earlier transactional test leaves TRUNCATE rows behind (backend.md,
Test order) and the setup writes skip the services on purpose.
"""

from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction

from cultures.audit.context import audit_context, audited_atomic, migration_audit
from cultures.audit.events import Change, record_event
from cultures.audit.management.commands.audit_reconcile import parse_since
from cultures.audit.models import ActorKind, Channel
from cultures.audit.reconcile import WITHOUT_EVENT, reconcile
from cultures.audit.registry import LAB_UPDATED
from cultures.labs import services as labs
from cultures.labs.models import Lab
from cultures.users.models import User

from .conftest import make_user

LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def db_now() -> datetime:
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        row = cursor.fetchone()
    assert row is not None
    moment: datetime = row[0]
    return moment


def run(*args: str) -> tuple[int, str]:
    out = StringIO()
    try:
        call_command("audit_reconcile", *args, stdout=out)
    except CommandError as error:
        return error.returncode, out.getvalue() + str(error)
    return 0, out.getvalue()


def lab_change(lab: Lab, changes: dict[str, list[object]] | None = None) -> Change:
    return Change("lab", lab.public_id, changes or {}, lab_id=lab.pk)


def service_write(admin: User) -> Lab:
    with audit_context(channel=Channel.COMMAND, actor=admin, reason="setup"):
        return labs.lab_create(name="Explained", code="EXP")


def raw_update(lab: Lab, *, actor_id: str = "", request_id: str = "") -> None:
    """A write that skips the services, from its own transaction."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.actor_id', %s, true), set_config('app.request_id', %s, true)",
            [actor_id, request_id],
        )
        cursor.execute("UPDATE labs_lab SET name = name || '!' WHERE id = %s", [lab.pk])


@pytest.mark.django_db(transaction=True)
def test_service_writes_are_clean() -> None:
    admin = make_user("reconcile-admin")
    since = db_now()
    lab = service_write(admin)
    with audit_context(channel=Channel.API, actor=admin):
        labs.lab_update(lab=lab, name="Renamed", code=lab.code)
    code, out = run("--since", since.isoformat())
    assert code == 0, out
    assert out.splitlines() == [f"since {since.isoformat()}: 0 alarms, 0 known"]


@pytest.mark.django_db(transaction=True)
def test_a_write_with_no_event_in_its_transaction_is_an_alarm() -> None:
    lab = service_write(make_user("reconcile-admin"))  # its event stays in the table
    since = db_now()
    raw_update(lab, request_id="psql-1")
    code, out = run("--since", since.isoformat())
    assert code == 1
    lines = out.splitlines()
    assert len(lines) == 2, out
    assert lines[0].startswith("no_event txid=")
    assert " table=labs.lab rows=1 " in lines[0]
    assert "db_role=cultures" in lines[0]
    assert lines[1].endswith("1 alarms, 0 known")


@pytest.mark.django_db(transaction=True)
def test_a_null_actor_next_to_user_events_is_an_alarm() -> None:
    admin = make_user("reconcile-admin")
    lab = Lab.objects.create(name="Lab", code="NUL")
    since = db_now()
    with audit_context(channel=Channel.API, actor=admin), audited_atomic():
        record_event(LAB_UPDATED, lab_change(lab))
        with connection.cursor() as cursor:  # the actor never reaches the trigger
            cursor.execute("SELECT set_config('app.actor_id', '', true)")
            cursor.execute("UPDATE labs_lab SET name = 'Changed' WHERE id = %s", [lab.pk])
    assert [(f.kind, f.table_label, f.rows) for f in reconcile(since)] == [
        ("no_actor", "labs.lab", 1)
    ]


@pytest.mark.django_db(transaction=True)
def test_an_invalid_actor_claim_is_an_alarm() -> None:
    admin = make_user("reconcile-admin")
    lab = Lab.objects.create(name="Lab", code="INV")
    since = db_now()
    with audit_context(channel=Channel.API, actor=admin), audited_atomic():
        record_event(LAB_UPDATED, lab_change(lab))
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.actor_id', 'not-a-number', true)")
            cursor.execute("UPDATE labs_lab SET name = 'Changed' WHERE id = %s", [lab.pk])
    assert [(f.kind, f.alarm) for f in reconcile(since)] == [("invalid_actor", True)]


@pytest.mark.django_db(transaction=True)
def test_a_data_migration_with_its_event_is_listed_as_known() -> None:
    lab = Lab.objects.create(name="Lab", code="MIG")
    since = db_now()
    with migration_audit("0099_rename_labs", reason="normalise names"):
        Lab.objects.filter(pk=lab.pk).update(name="LAB")  # a data migration's bulk change
        record_event(LAB_UPDATED, lab_change(lab, {"name": ["Lab", "LAB"]}))
    findings = reconcile(since)
    assert [(f.kind, f.alarm, f.table_label, f.channels, f.labels) for f in findings] == [
        ("known", False, "labs.lab", "migration", "migration:0099_rename_labs")
    ]
    code, out = run("--since", since.isoformat())
    assert code == 0, out
    assert out.splitlines()[0].startswith("known txid=")
    assert "channel=migration label='migration:0099_rename_labs'" in out
    assert out.splitlines()[-1].endswith("0 alarms, 1 known")


@pytest.mark.django_db(transaction=True)
def test_a_system_command_with_its_events_is_known_not_an_alarm() -> None:
    since = db_now()
    with audit_context(
        channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label="command:x"
    ):
        labs.lab_create(name="System", code="SYS")
    assert [(f.kind, f.channels, f.labels) for f in reconcile(since)] == [
        ("known", "command", "command:x")
    ]


@pytest.mark.django_db(transaction=True)
def test_since_leaves_out_older_changes() -> None:
    lab = Lab.objects.create(name="Lab", code="OLD")
    since = db_now()
    raw_update(lab)
    later = db_now() + timedelta(seconds=1)
    assert run("--since", later.isoformat())[0] == 0
    assert run("--since", since.isoformat())[0] == 1


@pytest.mark.django_db
def test_the_unexplained_query_is_an_anti_join_on_txid() -> None:
    """NOT IN cannot be planned as an anti join and scans the events per row change."""
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN " + WITHOUT_EVENT, [LONG_AGO])
        plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "Anti Join" in plan, plan
    assert "audit_auditevent" in plan


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("25h", datetime(2026, 10, 16, 5, 0, tzinfo=UTC)),
        ("7d", datetime(2026, 10, 10, 6, 0, tzinfo=UTC)),
        ("2026-10-01", datetime(2026, 10, 1, tzinfo=UTC)),
        ("2026-10-01T08:30:00+02:00", datetime(2026, 10, 1, 6, 30, tzinfo=UTC)),
        ("2026-10-01T08:30", datetime(2026, 10, 1, 8, 30, tzinfo=UTC)),
    ],
)
def test_since_accepts_hours_days_and_iso_dates(value: str, expected: datetime) -> None:
    assert parse_since(value, datetime(2026, 10, 17, 6, 0, tzinfo=UTC)) == expected


@pytest.mark.parametrize("value", ["yesterday", "25", "1w", "-1h"])
def test_since_refuses_anything_else(value: str) -> None:
    with pytest.raises(CommandError, match="--since"):
        parse_since(value, datetime(2026, 10, 17, tzinfo=UTC))

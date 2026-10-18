"""AuditEvent.strain_id, the root of a strain's timeline (ADR 0008, D13; migrations 0012, 0013).

No strain table exists yet, so the events here name a strain by a public id
only, as every later service will: a passage, batch or vial event carries the
id of the strain it belongs to.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.backends.utils import CursorWrapper
from model_bakery import baker

from cultures.audit.context import AuditContext
from cultures.audit.events import Change, record_batch, record_event
from cultures.audit.models import AuditEvent
from cultures.audit.registry import EVENT_TYPES, EventType
from cultures.labs.models import Lab

from .conftest import TEST_ROLES, refused
from .test_migration_secret_marker import migrate, query

pytestmark = pytest.mark.django_db

INDEX = "audit_event_strain_time_idx"
BEFORE = [("audit", "0011_reason_required_user_erased")]
# Test-only types, removed again by monkeypatch: no strain service exists yet.
VIAL_MOVED = EventType("test_vial_moved", "{actor} moved vial {subject}")
VIALS_MOVED = EventType("test_vials_moved", "{actor} moved {count} vials")


@pytest.fixture(autouse=True)
def vial_types(monkeypatch: pytest.MonkeyPatch) -> None:
    for kind in (VIAL_MOVED, VIALS_MOVED):
        monkeypatch.setitem(EVENT_TYPES, kind.code, kind)


@pytest.fixture
def lab() -> Lab:
    found: Lab = baker.make(Lab, name="Mycology", code="MYC")
    return found


def vial_change(lab: Lab | None, strain: uuid.UUID | None) -> Change:
    return Change(
        "vial",
        uuid.uuid4(),
        {"status": ["available", "reserved"]},
        lab_id=lab.pk if lab else None,
        strain_id=strain,
    )


def columns() -> list[tuple[Any, ...]]:
    return query(
        "SELECT data_type, is_nullable, column_default FROM information_schema.columns"
        " WHERE table_name = 'audit_auditevent' AND column_name = 'strain_id'"
    )


def index_definitions() -> list[tuple[Any, ...]]:
    return query(
        "SELECT pg_get_indexdef(i.indexrelid), i.indisvalid FROM pg_index i"
        " JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = %s",
        [INDEX],
    )


def test_the_column_is_a_nullable_uuid_without_a_default_or_a_foreign_key() -> None:
    assert columns() == [("uuid", "YES", None)]
    fks = query(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'audit_auditevent'::regclass"
        " AND contype = 'f' AND conkey = ARRAY[(SELECT attnum FROM pg_attribute"
        " WHERE attrelid = 'audit_auditevent'::regclass AND attname = 'strain_id')]::int2[]"
    )
    assert fks == []  # the strain table does not exist yet, and an event outlives its strain


def test_the_timeline_index_is_valid_and_partial() -> None:
    ((definition, valid),) = index_definitions()
    assert valid is True
    assert definition.endswith(
        "USING btree (lab_id, strain_id, occurred_at DESC) WHERE (strain_id IS NOT NULL)"
    )


def test_a_strain_timeline_query_uses_the_index(lab: Lab, audited: AuditContext) -> None:
    """strain_id = x implies the partial predicate, so the planner can take the index."""
    strain = uuid.uuid4()
    record_event(VIAL_MOVED, vial_change(lab, strain))
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")
        plan = (
            AuditEvent.objects.filter(lab_id__in=[lab.pk], strain_id=strain)
            .order_by("-occurred_at")
            .explain()
        )
    assert INDEX in plan


def test_record_event_stores_the_strain(lab: Lab, audited: AuditContext) -> None:
    strain = uuid.uuid4()
    event = record_event(VIAL_MOVED, vial_change(lab, strain))
    event.refresh_from_db()
    assert (event.strain_id, event.lab_id) == (strain, lab.pk)


def test_an_event_without_a_strain_stores_null(lab: Lab, audited: AuditContext) -> None:
    """Events about users and labs name no strain: Change defaults to None."""
    event = record_event(VIAL_MOVED, Change("lab", lab.public_id, {}, lab_id=lab.pk))
    event.refresh_from_db()
    assert event.strain_id is None


def test_a_batch_of_one_strain_puts_its_summary_on_that_timeline(
    lab: Lab, audited: AuditContext
) -> None:
    strain = uuid.uuid4()
    record_batch(VIAL_MOVED, VIALS_MOVED, [vial_change(lab, strain), vial_change(lab, strain)])
    rows = AuditEvent.objects.order_by("pk").values_list("event_type", "lab_id", "strain_id")
    assert list(rows) == [
        (VIAL_MOVED.code, lab.pk, strain),
        (VIAL_MOVED.code, lab.pk, strain),
        (VIALS_MOVED.code, lab.pk, strain),
    ]


def test_a_batch_across_strains_or_labs_gives_its_summary_neither(
    lab: Lab, audited: AuditContext
) -> None:
    other_lab: Lab = baker.make(Lab, name="Bacteriology", code="BAC")
    first, second = uuid.uuid4(), uuid.uuid4()
    record_batch(VIAL_MOVED, VIALS_MOVED, [vial_change(lab, first), vial_change(other_lab, second)])
    summary = AuditEvent.objects.get(event_type=VIALS_MOVED.code)
    assert (summary.lab_id, summary.strain_id) == (None, None)

    record_batch(VIAL_MOVED, VIALS_MOVED, [vial_change(lab, first), vial_change(lab, None)])
    summary = AuditEvent.objects.filter(event_type=VIALS_MOVED.code).latest("pk")
    assert (summary.lab_id, summary.strain_id) == (lab.pk, None)


@pytest.fixture
def strain_event(lab: Lab, audited: AuditContext) -> AuditEvent:
    return record_event(VIAL_MOVED, vial_change(lab, uuid.uuid4()))


def test_the_strain_cannot_be_rewritten_by_any_role(strain_event: AuditEvent) -> None:
    """The append-only trigger covers the new column: it refuses the row, not a column list."""
    with (
        pytest.raises(DatabaseError, match="audit_auditevent is append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("UPDATE audit_auditevent SET strain_id = NULL")
    strain_event_again = AuditEvent.objects.get(pk=strain_event.pk)
    assert strain_event_again.strain_id == strain_event.strain_id


def test_the_runtime_role_writes_the_strain_and_cannot_change_it(
    lab: Lab, audited: AuditContext, runtime_role: CursorWrapper
) -> None:
    """Table grants (SELECT, INSERT) cover the new column, UPDATE stays refused."""
    strain = uuid.uuid4()
    event = record_event(VIAL_MOVED, vial_change(lab, strain))
    runtime_role.execute("SELECT strain_id FROM audit_auditevent WHERE id = %s", [event.pk])
    assert runtime_role.fetchone() == (strain,)
    refused(
        runtime_role,
        "UPDATE audit_auditevent SET strain_id = NULL",
        "permission denied for table audit_auditevent",
    )
    runtime_role.execute("SELECT current_user")
    assert runtime_role.fetchone() == (TEST_ROLES.runtime,)


@pytest.fixture
def back_to_the_leaf() -> Iterator[None]:
    yield
    migrate()  # later tests need the current schema, whatever happened here


@pytest.mark.slow
@pytest.mark.migrations
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("back_to_the_leaf")
def test_the_strain_root_migrations_go_back_and_forth(lab: Lab, audited: AuditContext) -> None:
    record_event(VIAL_MOVED, vial_change(lab, uuid.uuid4()))

    migrate(BEFORE)
    assert index_definitions() == []
    assert columns() == []
    assert query("SELECT count(*) FROM audit_auditevent") == [(1,)]  # the event stays

    migrate()
    assert columns() == [("uuid", "YES", None)]
    ((_, valid),) = index_definitions()
    assert valid is True

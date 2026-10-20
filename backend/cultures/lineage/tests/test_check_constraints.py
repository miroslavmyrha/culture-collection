"""The database holds checks and the batch status on its own: constraints matched by name and
the guard triggers of migration 0006, written past the services with the ORM and raw SQL."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from cultures.audit.context import AuditContext
from cultures.lineage.models import Batch, BatchCheck, CheckKind, Passage
from cultures.users.models import User

from .support import MakeBatch, pass_all, record, vials_of

pytestmark = pytest.mark.django_db
DB_ERRORS = (IntegrityError, InternalError)


def sql(statement: str, params: list[Any] | None = None) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(statement, params or [])


def create(**fields: Any) -> BatchCheck:
    with transaction.atomic():
        return BatchCheck.objects.create(**fields)


@pytest.fixture
def batch(make_batch: MakeBatch, passage0: Passage) -> Batch:
    return make_batch(passage0, vial_count=2)


def check_fields(batch: Batch, user: User, **changes: Any) -> dict[str, Any]:
    return {
        "lab_id": batch.lab_id,
        "batch": batch,
        "kind": "viability",
        "stage": "after_preservation",
        "checked_on": date(2026, 10, 2),
        "performed_by": user,
        "method": "growth",
        "result": "pass",
        **changes,
    }


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"kind": "smell"}, "lineage_batchcheck_kind_valid"),
        ({"stage": "receipt"}, "lineage_batchcheck_stage_valid"),
        ({"result": "maybe"}, "lineage_batchcheck_result_valid"),
        ({"method": "maldi_tof"}, "lineage_batchcheck_method_of_kind"),
        ({"kind": "purity", "method": "growth"}, "lineage_batchcheck_method_of_kind"),
        ({"kind": "identity", "method": "streak_plate"}, "lineage_batchcheck_method_of_kind"),
        ({"method_detail": " TSA"}, "lineage_batchcheck_method_detail_trimmed"),
        ({"method": "other"}, "lineage_batchcheck_other_described"),
        ({"value": Decimal(3)}, "lineage_batchcheck_value_with_unit"),
        ({"unit": "percent"}, "lineage_batchcheck_value_with_unit"),
        ({"value": Decimal(-1), "unit": "cfu_per_ml"}, "lineage_batchcheck_value_with_unit"),
        ({"value": Decimal(3), "unit": "litres"}, "lineage_batchcheck_value_with_unit"),
        ({"value": Decimal(101), "unit": "percent"}, "lineage_batchcheck_percent_range"),
        ({"result": "reduced"}, "lineage_batchcheck_reduced_has_note"),
        ({"result": "reduced", "note": " "}, "lineage_batchcheck_reduced_has_note"),
        # A valid check has no reason. Other statuses: the trigger refuses them on insert, and
        # the update to entered in error without a reason is in the test after the next.
        ({"reason": "why"}, "lineage_batchcheck_reason_iff_in_error"),
    ],
)
def test_the_database_refuses_a_bad_check(
    batch: Batch, curator: User, changes: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        create(**check_fields(batch, curator, **changes))


def test_a_good_check_with_every_optional_field_is_stored(batch: Batch, curator: User) -> None:
    vial = vials_of(batch)[0]
    check = create(
        **check_fields(
            batch,
            curator,
            method="other",
            method_detail="Flow cytometry",
            value=Decimal(100),
            unit="percent",
            result="reduced",
            note="Fewer living cells than expected.",
            vial=vial,
        )
    )
    assert BatchCheck.objects.get(pk=check.pk).value == 100


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": "entered_in_error", "reason": "typo"}, "a check is recorded valid"),
        ({"checked_on": date(2026, 9, 30)}, "not dated before its batch was preserved"),
    ],
)
def test_the_trigger_refuses_a_check_that_cannot_be(
    batch: Batch, curator: User, changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(DB_ERRORS, match=message):
        create(**check_fields(batch, curator, **changes))


def test_a_check_is_in_the_lab_of_its_batch(batch: Batch, curator: User, other_lab: Any) -> None:
    with pytest.raises(DB_ERRORS, match="in the lab of its batch"):
        create(**check_fields(batch, curator, lab_id=other_lab.pk))


def test_the_vial_and_the_corrected_check_belong_to_the_batch(
    batch: Batch, make_batch: MakeBatch, curator: User
) -> None:
    other = make_batch(batch.passage, vial_count=1)
    with pytest.raises(DB_ERRORS, match="the vial of a check belongs to its batch"):
        create(**check_fields(batch, curator, vial=vials_of(other)[0]))
    elsewhere = create(**check_fields(other, curator))
    with pytest.raises(DB_ERRORS, match="supersedes a check of the same batch and kind"):
        create(**check_fields(batch, curator, supersedes=elsewhere))
    here = create(**check_fields(batch, curator, kind="purity", method="streak_plate"))
    with pytest.raises(DB_ERRORS, match="supersedes a check of the same batch and kind"):
        create(**check_fields(batch, curator, supersedes=here))
    same = create(**check_fields(batch, curator))
    assert create(**check_fields(batch, curator, supersedes=same)).supersedes == same
    with pytest.raises(IntegrityError, match="supersedes_id"):  # one correction per check
        create(**check_fields(batch, curator, supersedes=same))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE lineage_batchcheck SET result = 'fail'",
        "UPDATE lineage_batchcheck SET note = 'later'",
        "UPDATE lineage_batchcheck SET checked_on = '2026-10-05'",
        "UPDATE lineage_batchcheck SET status = 'entered_in_error', reason = 'x', note = 'y'",
        "UPDATE lineage_batchcheck SET reason = 'only the reason'",
    ],
)
def test_a_check_changes_only_by_being_entered_in_error(
    batch: Batch, curator: User, statement: str
) -> None:
    create(**check_fields(batch, curator))
    with pytest.raises(DB_ERRORS, match="changes only once, when it is entered in error"):
        sql(statement)


def test_entered_in_error_is_final_and_nothing_is_deleted(batch: Batch, curator: User) -> None:
    create(**check_fields(batch, curator))
    with pytest.raises(DB_ERRORS, match="lineage_batchcheck_reason_iff_in_error"):
        sql("UPDATE lineage_batchcheck SET status = 'entered_in_error'")
    sql("UPDATE lineage_batchcheck SET status = 'entered_in_error', reason = 'mix-up'")
    with pytest.raises(DB_ERRORS, match="changes only once"):
        sql("UPDATE lineage_batchcheck SET status = 'valid', reason = ''")
    with pytest.raises(DB_ERRORS, match="changes only once"):
        sql("UPDATE lineage_batchcheck SET reason = 'another reason'")
    with pytest.raises(DB_ERRORS, match="never deleted"):
        sql("DELETE FROM lineage_batchcheck")


# The batch status.


@pytest.mark.parametrize(
    "assignment",
    [
        "status = 'on_hold'",  # no reason, no time
        "status = 'on_hold', status_changed_at = now()",
        "status = 'on_hold', status_reason = ' ', status_changed_at = now()",
        "status_reason = 'why'",
        "status_changed_at = now()",
    ],
)
def test_every_status_after_the_first_has_a_reason_and_a_time(
    batch: Batch, assignment: str
) -> None:
    with pytest.raises(IntegrityError, match="lineage_batch_status_reason_once_changed"):
        sql(f"UPDATE lineage_batch SET {assignment}")  # noqa: S608 (constants)


def test_the_trigger_releases_only_after_three_passed_checks(
    batch: Batch, as_technician: AuditContext, technician: User
) -> None:
    release = (
        "UPDATE lineage_batch SET status = 'released', status_reason = 'ok',"
        " status_changed_at = now()"
    )
    with pytest.raises(DB_ERRORS, match="not of identity, purity, viability"):
        sql(release)
    _, purity, _ = pass_all(technician, batch)
    record(technician, batch, result="reduced")  # reduced counts as passed
    sql(
        "UPDATE lineage_batchcheck SET status = 'entered_in_error', reason = 'x' WHERE id = %s",
        [purity.pk],
    )
    with pytest.raises(DB_ERRORS, match="not of purity"):
        sql(release)
    record(technician, batch, CheckKind.PURITY)
    sql(release)
    assert Batch.objects.get(pk=batch.pk).status == "released"

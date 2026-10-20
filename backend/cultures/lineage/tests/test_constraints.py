"""The database holds batches, vials and placements on its own: constraints matched by name and
the guard triggers of migration 0004, written past the services with the ORM and raw SQL."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction
from django.utils import timezone

from cultures.labs.models import Lab
from cultures.lineage.models import Batch, Passage, Vial, VialPlacement, VialStatus
from cultures.storage.models import BoxType, StorageUnit, UnitKind
from cultures.storage.tests.conftest import Tree
from cultures.users.models import User

from .support import MakeBatch, vials_of

pytestmark = pytest.mark.django_db
DB_ERRORS = (IntegrityError, InternalError)


def sql(statement: str, params: list[Any] | None = None) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(statement, params or [])


def create(model: type[Any], **fields: Any) -> Any:
    with transaction.atomic():
        return model.objects.create(**fields)


# Passages: one of three sources.


def test_a_revived_passage_has_the_vial_as_its_only_source(
    passage0: Passage, make_batch: MakeBatch
) -> None:
    vial = vials_of(make_batch(passage0))[0]
    with pytest.raises(IntegrityError, match="lineage_passage_one_source"):
        create(
            Passage,
            lab_id=passage0.lab_id,
            strain=passage0.strain,
            number=1,
            source_passage=passage0,
            source_vial=vial,
        )
    revived = create(
        Passage, lab_id=passage0.lab_id, strain=passage0.strain, number=1, source_vial=vial
    )
    assert vial.revived_as == revived
    with pytest.raises(IntegrityError, match="source_vial_id"):
        create(Passage, lab_id=passage0.lab_id, strain=passage0.strain, number=1, source_vial=vial)


def test_a_passage_with_a_vial_never_changes(passage0: Passage, make_batch: MakeBatch) -> None:
    vial = vials_of(make_batch(passage0))[0]
    revived = create(
        Passage, lab_id=passage0.lab_id, strain=passage0.strain, number=1, source_vial=vial
    )
    with pytest.raises(DB_ERRORS, match="a passage never changes"):
        sql("UPDATE lineage_passage SET source_vial_id = NULL WHERE id = %s", [revived.pk])


# Batches.


def batch_fields(passage: Passage, **changes: Any) -> dict[str, Any]:
    return {
        "lab_id": passage.lab_id,
        "strain": passage.strain,
        "passage": passage,
        "number": 9,
        "method": "cryo_ln2",
        "cryoprotectant": "",
        "preserved_on": timezone.now().date(),
        "vial_count_created": 1,
        "purpose": "seed",
        **changes,
    }


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"number": 0}, "lineage_batch_number_positive"),
        ({"method": "dried"}, "lineage_batch_method_valid"),
        ({"purpose": "sale"}, "lineage_batch_purpose_valid"),
        (
            {"status": "gone", "status_reason": "why", "status_changed_at": timezone.now()},
            "lineage_batch_status_valid",
        ),
        ({"vial_count_created": 0}, "lineage_batch_vial_count_range"),
        ({"vial_count_created": 201}, "lineage_batch_vial_count_range"),
        ({"cryoprotectant": " glycerol"}, "lineage_batch_cryoprotectant_trimmed"),
    ],
)
def test_the_database_refuses_a_bad_batch(
    passage0: Passage, changes: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        create(Batch, **batch_fields(passage0, **changes))


def test_a_batch_number_is_unique_per_strain(passage0: Passage, make_batch: MakeBatch) -> None:
    batch = make_batch(passage0)
    with pytest.raises(IntegrityError, match="lineage_batch_strain_number_uniq"):
        create(Batch, **batch_fields(passage0, number=batch.number))


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("UPDATE lineage_batch SET number = 7", "changes only its status"),
        ("UPDATE lineage_batch SET purpose = 'seed'", "changes only its status"),
        ("UPDATE lineage_batch SET preserved_on = '2026-01-01'", "changes only its status"),
        ("DELETE FROM lineage_batch", "never deleted"),
    ],
)
def test_a_batch_changes_only_its_status(
    passage0: Passage, make_batch: MakeBatch, statement: str, message: str
) -> None:
    make_batch(passage0)
    with pytest.raises(DB_ERRORS, match=message):
        sql(statement)
    sql(
        "UPDATE lineage_batch SET status = 'on_hold', status_reason = 'contamination seen',"
        " status_changed_at = now()"
    )
    assert Batch.objects.get().status == "on_hold"


# Vials.


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"seq": 0}, "lineage_vial_seq_positive"),
        ({"status": "gone", "status_changed_at": timezone.now()}, "lineage_vial_status_valid"),
        ({"barcode": "A B"}, "lineage_vial_barcode_no_spaces"),
        ({"status": "lost"}, "lineage_vial_changed_at_once_changed"),
    ],
)
def test_the_database_refuses_a_bad_vial(
    passage0: Passage, make_batch: MakeBatch, changes: dict[str, Any], constraint: str
) -> None:
    batch = make_batch(passage0)
    with pytest.raises(IntegrityError, match=constraint):
        create(Vial, **{"lab_id": batch.lab_id, "batch": batch, "seq": 9, **changes})


def test_seq_is_unique_per_batch_and_a_barcode_per_lab(
    passage0: Passage, make_batch: MakeBatch
) -> None:
    first, second = make_batch(passage0), make_batch(passage0)
    with pytest.raises(IntegrityError, match="lineage_vial_batch_seq_uniq"):
        create(Vial, lab_id=first.lab_id, batch=first, seq=1)
    create(Vial, lab_id=first.lab_id, batch=first, seq=9, barcode="TUBE-1")
    with pytest.raises(IntegrityError, match="lineage_vial_lab_barcode_uniq"):
        create(Vial, lab_id=second.lab_id, batch=second, seq=9, barcode="TUBE-1")
    # Many vials have none.
    create(Vial, lab_id=second.lab_id, batch=second, seq=10, barcode=None)
    create(Vial, lab_id=second.lab_id, batch=second, seq=11, barcode=None)


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("UPDATE lineage_vial SET seq = 9 WHERE seq = 1", "keeps its lab, batch and number"),
        ("UPDATE lineage_vial SET public_id = gen_random_uuid()", "keeps its lab, batch"),
        ("DELETE FROM lineage_vial", "never deleted"),
    ],
)
def test_a_vial_keeps_its_identity(
    passage0: Passage, make_batch: MakeBatch, statement: str, message: str
) -> None:
    make_batch(passage0)
    with pytest.raises(DB_ERRORS, match=message):
        sql(statement)


def test_a_barcode_may_change_in_the_database(passage0: Passage, make_batch: MakeBatch) -> None:
    make_batch(passage0, vial_count=1)
    sql("UPDATE lineage_vial SET barcode = 'X-1'")
    assert Vial.objects.get().barcode == "X-1"


def test_a_vial_leaves_its_box_only_once_the_placement_is_closed(
    passage0: Passage, make_batch: MakeBatch, tree: Tree
) -> None:
    vial = vials_of(make_batch(passage0, vial_count=1, box=tree.box))[0]
    with pytest.raises(DB_ERRORS, match="close the placement before the vial leaves its box"):
        sql(
            "UPDATE lineage_vial SET status = 'consumed', status_changed_at = now() WHERE id = %s",
            [vial.pk],
        )
    # Quarantined keeps its place.
    sql(
        "UPDATE lineage_vial SET status = 'quarantined', status_changed_at = now() WHERE id = %s",
        [vial.pk],
    )


# Placements.


def placement_fields(vial: Vial, box: StorageUnit, user: User, **changes: Any) -> dict[str, Any]:
    return {
        "lab_id": vial.lab_id,
        "vial": vial,
        "box": box,
        "row": 1,
        "col": 1,
        "placed_at": timezone.now(),
        "placed_by": user,
        **changes,
    }


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"row": 0}, "lineage_placement_position_positive"),
        ({"col": 0}, "lineage_placement_position_positive"),
        ({"removal_reason": "moved"}, "lineage_placement_removal_complete"),
        ({"removed_at": "now"}, "lineage_placement_removal_complete"),
        (
            {"removed_at": "before", "removal_reason": "moved"},
            "lineage_placement_removed_after_placed",
        ),
    ],
)
def test_the_database_refuses_a_bad_placement(
    *,
    passage0: Passage,
    make_batch: MakeBatch,
    tree: Tree,
    curator: User,
    changes: dict[str, Any],
    constraint: str,
) -> None:
    vial = vials_of(make_batch(passage0, vial_count=1))[0]
    fields = placement_fields(vial, tree.box, curator, **changes)
    now = timezone.now()
    if changes.get("removed_at") == "now":
        fields["removed_at"] = now
    if changes.get("removed_at") == "before":
        fields.update(removed_at=now - timedelta(days=1), removed_by=curator)
    with pytest.raises(IntegrityError, match=constraint):
        create(VialPlacement, **fields)


def test_one_open_placement_per_vial_and_per_position(
    passage0: Passage, make_batch: MakeBatch, tree: Tree, curator: User
) -> None:
    first, second = vials_of(make_batch(passage0, vial_count=2))
    create(VialPlacement, **placement_fields(first, tree.box, curator))
    with pytest.raises(IntegrityError, match="lineage_placement_one_open_per_position"):
        create(VialPlacement, **placement_fields(second, tree.box, curator))
    with pytest.raises(IntegrityError, match="lineage_placement_one_open_per_vial"):
        create(VialPlacement, **placement_fields(first, tree.box, curator, row=2))
    # A closed row blocks neither.
    VialPlacement.objects.filter(vial=first).update(
        removed_at=timezone.now(), removed_by=curator, removal_reason="moved"
    )
    create(VialPlacement, **placement_fields(second, tree.box, curator))
    create(VialPlacement, **placement_fields(first, tree.box, curator, row=2))


Changes = Callable[[Tree, Lab], dict[str, Any]]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (lambda t, other: {"box": t.rack}, "placed in boxes only"),
        (lambda t, other: {"box": t.freezer}, "placed in boxes only"),
        (lambda t, other: {"row": 10}, r"position 10,1 is outside the box of 9 x 9"),
        (lambda t, other: {"col": 10}, r"outside the box of 9 x 9"),
        (lambda t, other: {"lab_id": other.pk}, "in one lab"),
    ],
)
def test_the_placement_trigger_checks_the_box(
    *,
    passage0: Passage,
    make_batch: MakeBatch,
    tree: Tree,
    other_lab: Lab,
    curator: User,
    changes: Changes,
    message: str,
) -> None:
    vial = vials_of(make_batch(passage0, vial_count=1))[0]
    fields = {**placement_fields(vial, tree.box, curator), **changes(tree, other_lab)}
    with pytest.raises(DB_ERRORS, match=message):
        create(VialPlacement, **fields)


def test_the_placement_trigger_refuses_a_box_of_another_lab(
    passage0: Passage, make_batch: MakeBatch, other_lab: Lab, curator: User, box_9x9: BoxType
) -> None:
    vial = vials_of(make_batch(passage0, vial_count=1))[0]
    freezer = create(StorageUnit, lab=other_lab, kind=UnitKind.FREEZER, name="F", max_risk_group=2)
    box = create(
        StorageUnit,
        lab=other_lab,
        kind=UnitKind.BOX,
        name="B",
        parent=freezer,
        box_type=box_9x9,
        rows=9,
        cols=9,
    )
    with pytest.raises(DB_ERRORS, match="in one lab"):
        create(VialPlacement, **placement_fields(vial, box, curator))


# The edges to each state from available, as the trigger allows them.
PATHS: dict[str, list[str]] = {
    "available": [],
    "reserved": ["reserved"],
    "consumed": ["consumed"],
    "quarantined": ["quarantined"],
    "to_destroy": ["to_destroy"],
    "destroyed": ["to_destroy", "destroyed"],
    "lost": ["lost"],
    "distributed": ["reserved", "distributed"],
    "entered_in_error": ["entered_in_error"],
}


def test_every_state_has_a_path() -> None:
    assert sorted(PATHS) == sorted(VialStatus.values)


@pytest.mark.usefixtures("vial_edges_alone")
@pytest.mark.parametrize("status", sorted(PATHS))
def test_a_vial_out_of_the_collection_gets_no_open_placement(
    passage0: Passage, make_batch: MakeBatch, tree: Tree, curator: User, status: str
) -> None:
    vial = vials_of(make_batch(passage0, vial_count=1))[0]
    for step in PATHS[status]:
        sql(
            "UPDATE lineage_vial SET status = %s, status_changed_at = now() WHERE id = %s",
            [step, vial.pk],
        )
    fields = placement_fields(vial, tree.box, curator)
    if status in ("consumed", "destroyed", "distributed", "entered_in_error", "lost"):
        with pytest.raises(DB_ERRORS, match=f"a {status} vial has no place in a box"):
            create(VialPlacement, **fields)
    else:
        create(VialPlacement, **fields)


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("UPDATE lineage_vialplacement SET row = 2", "changes only once, when it is closed"),
        ("UPDATE lineage_vialplacement SET box_id = box_id", None),
        ("DELETE FROM lineage_vialplacement", "never deleted"),
    ],
)
def test_a_placement_changes_once_when_it_is_closed(
    passage0: Passage, make_batch: MakeBatch, tree: Tree, statement: str, message: str | None
) -> None:
    make_batch(passage0, vial_count=1, box=tree.box)
    if message is None:
        sql(statement)  # the same values: nothing changed
        return
    with pytest.raises(DB_ERRORS, match=message):
        sql(statement)


def test_a_closed_placement_never_changes_again(
    passage0: Passage, make_batch: MakeBatch, tree: Tree, curator: User
) -> None:
    make_batch(passage0, vial_count=1, box=tree.box)
    sql(
        "UPDATE lineage_vialplacement SET removed_at = clock_timestamp(), removed_by_id = %s,"
        " removal_reason = 'moved'",
        [curator.pk],
    )
    with pytest.raises(DB_ERRORS, match="changes only once"):
        sql("UPDATE lineage_vialplacement SET removal_reason = 'lost'")

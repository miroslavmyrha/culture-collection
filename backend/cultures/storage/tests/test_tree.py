"""The tree holds in the database itself (migration 0003), whoever writes: raw SQL here, so no
service runs. Paths follow every insert and move, also of everything below a moved unit;
a cycle, a parent in another lab and a kind the parent may not hold are refused; units are
never deleted, keep their lab and kind, and a retired unit changes no more."""

import itertools
from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from cultures.labs.models import Lab
from cultures.storage.models import KIND_SPEC, BoxType, StorageUnit, UnitKind, may_hold

from .conftest import MakeUnit, Tree, fresh

pytestmark = pytest.mark.django_db


def sql(statement: str, *params: Any) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(statement, params)


def refused(message: str) -> Any:
    """The triggers raise check_violation or restrict_violation: IntegrityError in psycopg."""
    return pytest.raises((IntegrityError, InternalError), match=message)


def path_of(unit: StorageUnit) -> list[int]:
    return list(fresh(unit).path)


def test_a_new_unit_gets_the_path_from_its_root(tree: Tree) -> None:
    assert path_of(tree.freezer) == [tree.freezer.pk]
    assert path_of(tree.rack) == [tree.freezer.pk, tree.rack.pk]
    assert path_of(tree.box) == [tree.freezer.pk, tree.rack.pk, tree.box.pk]


def test_a_move_by_sql_rewrites_the_paths_of_everything_below(
    tree: Tree, make_unit: MakeUnit
) -> None:
    other = make_unit(UnitKind.LN2_TANK, "Tank B")
    second_box = make_unit(UnitKind.BOX, "Box 2", tree.rack)
    sql("UPDATE storage_storageunit SET parent_id = %s WHERE id = %s", other.pk, tree.rack.pk)
    assert path_of(tree.rack) == [other.pk, tree.rack.pk]
    assert path_of(tree.box) == [other.pk, tree.rack.pk, tree.box.pk]
    assert path_of(second_box) == [other.pk, tree.rack.pk, second_box.pk]
    assert path_of(tree.freezer) == [tree.freezer.pk]  # the old root is untouched
    # One level up: the box straight into the tank, its own path only.
    sql(
        "UPDATE storage_storageunit SET parent_id = %s, slot = NULL WHERE id = %s",
        other.pk,
        tree.box.pk,
    )
    assert path_of(tree.box) == [other.pk, tree.box.pk]
    assert path_of(second_box) == [other.pk, tree.rack.pk, second_box.pk]


def test_a_unit_never_goes_inside_itself(tree: Tree) -> None:
    with refused("a unit cannot go inside itself or a unit it holds"):
        sql("UPDATE storage_storageunit SET parent_id = id WHERE id = %s", tree.rack.pk)


def test_a_unit_never_goes_inside_a_unit_below_it(tree: Tree) -> None:
    """The kind spec alone would refuse a rack in a box too: the cycle guard speaks first,
    so it holds also if a later kind may hold its own kind."""
    with refused("a unit cannot go inside itself or a unit it holds"):
        sql(
            "UPDATE storage_storageunit SET parent_id = %s WHERE id = %s", tree.box.pk, tree.rack.pk
        )
    assert path_of(tree.rack) == [tree.freezer.pk, tree.rack.pk]


def test_a_parent_in_another_lab_is_refused(
    tree: Tree, make_unit: MakeUnit, other_lab: Lab, outsider: Any
) -> None:
    elsewhere = make_unit(UnitKind.FREEZER, "Freezer B", lab=other_lab, actor=outsider)
    with refused("a unit and the unit holding it are in the same lab"):
        sql(
            "UPDATE storage_storageunit SET parent_id = %s WHERE id = %s",
            elsewhere.pk,
            tree.rack.pk,
        )


def test_a_parent_that_does_not_exist_is_refused_at_once(tree: Tree) -> None:
    with refused("does not exist"):
        sql("UPDATE storage_storageunit SET parent_id = 999999 WHERE id = %s", tree.box.pk)


def test_a_path_written_by_hand_is_refused(tree: Tree) -> None:
    with refused("the path follows the parent"):
        sql(
            "UPDATE storage_storageunit SET path = ARRAY[%s]::bigint[] WHERE id = %s",
            tree.box.pk,
            tree.box.pk,
        )


PAIRS = list(itertools.product(UnitKind, UnitKind))
HELD = [(h, k) for h, k in PAIRS if may_hold(h, k)]
NOT_HELD = [(h, k) for h, k in PAIRS if not may_hold(h, k)]


def holder_of(lab: Lab, holder: UnitKind, box_type: BoxType) -> StorageUnit:
    """A raw unit of the kind: a rack or box needs a parent, so a freezer is above it."""
    if not KIND_SPEC[holder].held_by:
        return StorageUnit.objects.create(lab=lab, kind=holder, name="holder", max_risk_group=2)
    root = StorageUnit.objects.create(lab=lab, kind=UnitKind.FREEZER, name="root", max_risk_group=2)
    return StorageUnit.objects.create(
        lab=lab, kind=holder, name="holder", parent=root, **grid(holder, box_type)
    )


def insert_under(lab: Lab, parent: StorageUnit, kind: UnitKind, box_type: BoxType) -> None:
    with transaction.atomic():
        StorageUnit.objects.create(
            lab=lab, kind=kind, name="child", parent=parent, **grid(kind, box_type)
        )


@pytest.mark.parametrize(("holder", "kind"), HELD, ids=[f"{h}-holds-{k}" for h, k in HELD])
def test_the_trigger_lets_every_pair_of_the_kind_spec_through(
    lab: Lab, box_9x9: BoxType, holder: UnitKind, kind: UnitKind
) -> None:
    insert_under(lab, holder_of(lab, holder, box_9x9), kind, box_9x9)


@pytest.mark.parametrize(
    ("holder", "kind"), NOT_HELD, ids=[f"{h}-never-holds-{k}" for h, k in NOT_HELD]
)
def test_the_trigger_refuses_every_pair_the_kind_spec_does_not_name(
    lab: Lab, box_9x9: BoxType, holder: UnitKind, kind: UnitKind
) -> None:
    parent = holder_of(lab, holder, box_9x9)
    with refused(f"a {holder} cannot hold a {kind}"):
        insert_under(lab, parent, kind, box_9x9)


def grid(kind: UnitKind, box_type: BoxType) -> dict[str, Any]:
    if KIND_SPEC[kind].grid:
        return {"box_type": box_type, "rows": box_type.rows, "cols": box_type.cols}
    return {}


def test_the_kind_spec_reads_as_the_issue_says() -> None:
    assert may_hold(UnitKind.FREEZER, UnitKind.RACK)
    assert may_hold(UnitKind.LN2_TANK, UnitKind.RACK)
    assert may_hold(UnitKind.RACK, UnitKind.BOX)
    assert not may_hold(UnitKind.BOX, UnitKind.FREEZER)
    assert not may_hold(UnitKind.BOX, UnitKind.BOX)
    assert not may_hold(UnitKind.RACK, UnitKind.RACK)
    assert {k for k, spec in KIND_SPEC.items() if not spec.held_by} == {
        UnitKind.FREEZER,
        UnitKind.LN2_TANK,
    }
    assert [k for k, spec in KIND_SPEC.items() if spec.grid] == [UnitKind.BOX]


GUARDED = [
    ("DELETE FROM storage_storageunit WHERE id = %s", "never deleted"),
    (
        "UPDATE storage_storageunit SET public_id = gen_random_uuid() WHERE id = %s",
        "keeps its public id",
    ),
    (
        "UPDATE storage_storageunit SET kind = 'freezer', parent_id = NULL, slot = NULL"
        " WHERE id = %s",
        "keeps its kind",
    ),
]


@pytest.mark.parametrize(("statement", "message"), GUARDED, ids=[m for _, m in GUARDED])
def test_the_guard_holds_for_every_writer(tree: Tree, statement: str, message: str) -> None:
    with refused(message):
        sql(statement, tree.rack.pk)


def test_a_unit_stays_in_its_lab(tree: Tree, other_lab: Lab) -> None:
    with refused("a unit stays in its lab"):
        sql(
            "UPDATE storage_storageunit SET lab_id = %s WHERE id = %s",
            other_lab.pk,
            tree.freezer.pk,
        )


def test_a_retired_unit_changes_no_more_but_moves_with_its_parent(
    tree: Tree, make_unit: MakeUnit
) -> None:
    sql(
        "UPDATE storage_storageunit SET status = 'retired', retired_at = now() WHERE id = %s",
        tree.box.pk,
    )
    for statement in (
        "UPDATE storage_storageunit SET name = 'renamed' WHERE id = %s",
        "UPDATE storage_storageunit SET status = 'active', retired_at = NULL WHERE id = %s",
    ):
        with refused("a retired unit changes no more"):
            sql(statement, tree.box.pk)
    tank = make_unit(UnitKind.LN2_TANK, "Tank B")
    sql("UPDATE storage_storageunit SET parent_id = %s WHERE id = %s", tank.pk, tree.rack.pk)
    assert path_of(tree.box) == [tank.pk, tree.rack.pk, tree.box.pk]


def test_a_box_type_keeps_its_size_and_is_never_deleted(box_9x9: BoxType) -> None:
    for statement, message in (
        ("UPDATE storage_boxtype SET rows = 10 WHERE id = %s", "keeps its public id and its size"),
        ("UPDATE storage_boxtype SET cols = 8 WHERE id = %s", "keeps its public id and its size"),
        ("DELETE FROM storage_boxtype WHERE id = %s", "never deleted"),
    ):
        with refused(message):
            sql(statement, box_9x9.pk)
    sql("UPDATE storage_boxtype SET name = 'Renamed' WHERE id = %s", box_9x9.pk)

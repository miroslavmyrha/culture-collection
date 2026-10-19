"""The database refuses a storage row that cannot be true, also when the services are skipped:
a constraint for every invariant of one row, matched by its name."""

from typing import Any

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from cultures.labs.models import Lab
from cultures.storage.models import BoxType, StorageUnit, UnitKind, UnitStatus

from .conftest import Tree

pytestmark = pytest.mark.django_db


def refused(constraint: str) -> Any:
    return pytest.raises(IntegrityError, match=constraint)


def raw_unit(lab: Lab, **fields: Any) -> StorageUnit:
    values: dict[str, Any] = {
        "lab": lab,
        "kind": UnitKind.FREEZER,
        "name": "raw",
        "max_risk_group": 2,
        **fields,
    }
    with transaction.atomic():
        return StorageUnit.objects.create(**values)


def raw_box(lab: Lab, parent: StorageUnit, type_: BoxType, **fields: Any) -> StorageUnit:
    values: dict[str, Any] = {
        "kind": UnitKind.BOX,
        "parent": parent,
        "box_type": type_,
        "rows": 9,
        "cols": 9,
        "max_risk_group": None,
        **fields,
    }
    return raw_unit(lab, **values)


ROW_CASES = [
    ("storage_unit_kind_valid", {"kind": "shelf"}),
    ("storage_unit_status_valid", {"status": "lost"}),
    ("storage_unit_retired_at_iff_retired", {"status": UnitStatus.RETIRED}),
    ("storage_unit_retired_at_iff_retired", {"retired_at": timezone.now()}),
    ("storage_unit_name_trimmed", {"name": " Freezer"}),
    ("storage_unit_name_trimmed", {"name": ""}),
    ("storage_unit_barcode_no_spaces", {"barcode": "FR 01"}),
    ("storage_unit_barcode_no_spaces", {"barcode": ""}),
    ("storage_unit_roots_are_freezers_or_tanks", {"kind": UnitKind.RACK}),
    ("storage_unit_root_has_no_slot", {"slot": 1}),
    ("storage_unit_root_has_max_risk_group", {"max_risk_group": None}),
    ("storage_unit_max_risk_group_1_to_4", {"max_risk_group": 0}),
    ("storage_unit_max_risk_group_1_to_4", {"max_risk_group": 5}),
    ("storage_unit_temperature_range", {"temperature_c": -274}),
    ("storage_unit_temperature_range", {"temperature_c": 101}),
    ("storage_unit_grid_iff_box", {"rows": 9, "cols": 9}),
]


@pytest.mark.parametrize(("constraint", "fields"), ROW_CASES, ids=[c for c, _ in ROW_CASES])
def test_a_root_row_that_cannot_be_true_is_refused(
    lab: Lab, constraint: str, fields: dict[str, Any]
) -> None:
    with refused(constraint):
        raw_unit(lab, **fields)


def test_the_limits_themselves_are_accepted(lab: Lab) -> None:
    raw_unit(lab, name="cold", temperature_c=-273, max_risk_group=1)
    raw_unit(lab, name="warm", kind=UnitKind.LN2_TANK, temperature_c=100, max_risk_group=4)


BOX_CASES = [
    ("storage_unit_grid_iff_box", {"box_type": None}),
    ("storage_unit_grid_iff_box", {"rows": None}),
    ("storage_unit_grid_iff_box", {"cols": None}),
    ("storage_unit_grid_iff_box", {"rows": 0}),
    ("storage_unit_grid_iff_box", {"cols": 27}),
    ("storage_unit_slot_positive", {"slot": 0}),
]


@pytest.mark.parametrize(("constraint", "fields"), BOX_CASES, ids=[c for c, _ in BOX_CASES])
def test_a_box_without_its_size_is_refused(
    lab: Lab, tree: Tree, box_9x9: BoxType, constraint: str, fields: dict[str, Any]
) -> None:
    with refused(constraint):
        raw_box(lab, tree.rack, box_9x9, name="raw box", **fields)


def test_names_are_unique_per_parent_ignoring_case_and_retired_units_free_theirs(
    lab: Lab, tree: Tree, box_9x9: BoxType
) -> None:
    with refused("storage_unit_name_uniq"):
        raw_box(lab, tree.rack, box_9x9, name="BOX 1")
    raw_box(lab, tree.freezer, box_9x9, name="Box 1")  # another parent
    StorageUnit.objects.filter(pk=tree.box.pk).update(
        status=UnitStatus.RETIRED, retired_at=timezone.now()
    )
    raw_box(lab, tree.rack, box_9x9, name="box 1")  # the retired one no longer blocks it


def test_root_names_are_unique_per_lab(lab: Lab, other_lab: Lab, tree: Tree) -> None:
    with refused("storage_unit_name_uniq"):
        raw_unit(lab, name="freezer a")
    raw_unit(other_lab, name="Freezer A")


def test_a_slot_holds_one_unit_until_it_is_retired(lab: Lab, tree: Tree, box_9x9: BoxType) -> None:
    with refused("storage_unit_slot_uniq"):
        raw_box(lab, tree.rack, box_9x9, name="Box 2", slot=1)
    raw_box(lab, tree.rack, box_9x9, name="Box 2")  # no slot: none taken
    raw_box(lab, tree.rack, box_9x9, name="Box 3")
    StorageUnit.objects.filter(pk=tree.box.pk).update(
        status=UnitStatus.RETIRED, retired_at=timezone.now()
    )
    raw_box(lab, tree.rack, box_9x9, name="Box 4", slot=1)


def test_barcodes_are_unique_per_lab(lab: Lab, other_lab: Lab) -> None:
    raw_unit(lab, name="one", barcode="FRZ-0001")
    with refused("storage_unit_barcode_uniq"):
        raw_unit(lab, name="two", barcode="FRZ-0001")
    raw_unit(other_lab, name="one", barcode="FRZ-0001")
    raw_unit(lab, name="no barcode")
    raw_unit(lab, name="no barcode either")


BOX_TYPE_CASES = [
    ("storage_boxtype_name_trimmed", {"name": "9x9 "}),
    ("storage_boxtype_size", {"rows": 0}),
    ("storage_boxtype_size", {"rows": 27}),
    ("storage_boxtype_size", {"cols": 0}),
    ("storage_boxtype_size", {"cols": 27}),
]


@pytest.mark.parametrize(
    ("constraint", "fields"), BOX_TYPE_CASES, ids=[c for c, _ in BOX_TYPE_CASES]
)
def test_a_box_type_that_cannot_be_true_is_refused(constraint: str, fields: dict[str, Any]) -> None:
    with refused(constraint), transaction.atomic():
        BoxType.objects.create(**{"name": "9x9", "rows": 9, "cols": 9, **fields})


def test_box_type_names_are_unique_ignoring_case(box_9x9: BoxType) -> None:
    with refused("storage_boxtype_name_uniq"), transaction.atomic():
        BoxType.objects.create(name="CRYOBOX 9 X 9", rows=9, cols=9)

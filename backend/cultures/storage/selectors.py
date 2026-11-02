"""Reads of storage. Every one takes the access object, so the lab scope is in the signature."""

from collections.abc import Iterable
from dataclasses import dataclass

from django.db.models import Count, F, Q, QuerySet

from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm

from .models import BoxType, StorageUnit, UnitKind, UnitStatus


def unit_tree(*, access: Access, lab: Lab) -> QuerySet[StorageUnit]:
    """Every unit of one lab the user may view, retired ones included, in tree order: each
    unit right after the one holding it, siblings by id. With the parent's public id, the box
    type and the facts of the whole path, in one query."""
    return (
        StorageUnit.objects.for_access(access, Perm.VIEW_STORAGE)
        .filter(lab=lab)
        .select_related("box_type")
        .annotate(parent_public_id=F("parent__public_id"))
        .with_path_facts()
        .order_by("path")
    )


def unit_path(unit: StorageUnit) -> list[StorageUnit]:
    """The units from the root down to the unit's parent: its breadcrumbs. One query."""
    above = {u.pk: u for u in StorageUnit.objects.filter(pk__in=unit.path[:-1])}
    return [above[pk] for pk in unit.path[:-1]]


def unit_children(unit: StorageUnit) -> QuerySet[StorageUnit]:
    """What the unit holds, by slot (units without one last), then name."""
    return (
        StorageUnit.objects.filter(parent=unit)
        .select_related("box_type")
        .order_by(F("slot").asc(nulls_last=True), "name", "pk")
    )


@dataclass(frozen=True)
class Counts:
    """What a unit holds, itself and everything below it (#80). Retired boxes count nowhere:
    one holds no vial (services.unit_set_status) and takes none."""

    # Boxes below the unit: 0 for a box.
    boxes: int
    # Vials with an open placement in the unit or below it, of every strain. A count is no
    # location: the box grid shows the same positions as taken (ADR 0009, amendment of
    # 2026-10-20).
    vials: int
    # Positions of those boxes, the unit's own if it is a box, that hold no vial.
    free_positions: int


def unit_counts(units: Iterable[StorageUnit]) -> dict[int, Counts]:
    """The counts of each unit by its id, in one query whatever the number of units: every box
    whose path passes through one of them, with its open placements, summed up the path."""
    wanted = {unit.pk: unit.lab_id for unit in units}
    if not wanted:
        return {}
    held = (
        StorageUnit.objects.filter(
            lab_id__in=set(wanted.values()), kind=UnitKind.BOX, path__overlap=list(wanted)
        )
        .exclude(status=UnitStatus.RETIRED)
        .annotate(taken=Count("placements", filter=Q(placements__removed_at__isnull=True)))
        .values_list("pk", "path", "rows", "cols", "taken")
        .order_by()
    )
    sums = {pk: [0, 0, 0] for pk in wanted}  # boxes, vials, positions
    for box, path, rows, cols, taken in held:
        for pk in path:
            total = sums.get(pk)
            if total is None:
                continue
            total[0] += pk != box
            total[1] += taken
            total[2] += (rows or 0) * (cols or 0)  # a box has both: storage_unit_grid_iff_box
    return {
        pk: Counts(boxes=boxes, vials=vials, free_positions=positions - vials)
        for pk, (boxes, vials, positions) in sums.items()
    }


def units_to_manage(access: Access) -> QuerySet[StorageUnit]:
    """The units the user may put something into or move: any lab where they manage storage.
    The service still checks that a parent is in the unit's own lab."""
    return StorageUnit.objects.for_access(access, Perm.MANAGE_STORAGE)


def box_type_list() -> QuerySet[BoxType]:
    """Box types are global: every signed-in user reads them, by name."""
    return BoxType.objects.order_by("name", "pk")

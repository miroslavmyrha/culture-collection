"""What seed_dev and seed_e2e make of storage, through the storage services: box types and
storage trees (freezers and tanks, racks, boxes).

Found again by natural keys, so a second run creates nothing twice: a box type by its name in
any case, a unit by its lab, its parent and its name. Neither is ever changed again: a unit's
status is set once, by the run that created it.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from cultures.labs.access import Access
from cultures.labs.models import Lab

from . import services
from .models import BoxType, StorageUnit, UnitKind, UnitStatus


@dataclass(frozen=True)
class SeedUnit:
    kind: UnitKind
    name: str
    slot: int | None = None
    barcode: str = ""
    temperature_c: int | None = None
    max_risk_group: int | None = None
    box_type: str | None = None  # the box type's name
    # Set after what the unit holds (nothing goes into a unit out of service), with a reason.
    status: UnitStatus | None = None
    reason: str = ""
    children: Sequence["SeedUnit"] = field(default_factory=tuple)


def box_type(name: str, rows: int, cols: int) -> None:
    if not BoxType.objects.filter(name__iexact=name).exists():
        services.box_type_create(name=name, rows=rows, cols=cols)


def unit(
    access: Access, lab: Lab, data: SeedUnit, parent: StorageUnit | None
) -> tuple[StorageUnit, bool]:
    """The unit alone, without what it holds and its status; True when this run made it."""
    found = StorageUnit.objects.filter(lab=lab, parent=parent, name=data.name).first()
    if found is not None:
        return found, False
    made = services.unit_create(
        access=access,
        lab=lab,
        data=services.NewUnit(
            kind=data.kind,
            name=data.name,
            parent=parent,
            slot=data.slot,
            barcode=data.barcode,
            temperature_c=data.temperature_c,
            max_risk_group=data.max_risk_group,
            box_type=BoxType.objects.get(name=data.box_type) if data.box_type else None,
        ),
    )
    return made, True


def tree(
    access: Access, lab: Lab, units: Sequence[SeedUnit], parent: StorageUnit | None = None
) -> tuple[int, int]:
    """The units with what they hold, depth first, each status set after its unit's contents.
    Returns how many units were created and how many found."""
    created = found = 0
    for data in units:
        made, new = unit(access, lab, data, parent)
        created, found = created + new, found + (not new)
        below = tree(access, lab, data.children, made)
        created, found = created + below[0], found + below[1]
        if new and data.status is not None:
            services.unit_set_status(
                access=access, unit=made, status=data.status, reason=data.reason
            )
    return created, found


def unit_at(lab: Lab, names: Sequence[str]) -> StorageUnit:
    """The unit at this path of names, from a top unit down."""
    found = None
    for name in names:
        found = StorageUnit.objects.get(lab=lab, parent=found, name=name)
    assert found is not None  # noqa: S101 (a path names at least one unit)
    return found

"""Where a vial is, and the reveal of a regulated strain's location (ADR 0009)."""

from dataclasses import dataclass

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    VIAL_LOCATION_REVEALED,
)
from cultures.core.exceptions import Forbidden
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.permissions import Perm
from cultures.labs.services import holds_location_grant
from cultures.storage.models import StorageUnit
from cultures.strains.models import Strain
from cultures.strains.selectors import regulating_restrictions

from ..models import (
    Vial,
    VialPlacement,
)
from ._shared import (
    VIAL,
    _require,
)


@dataclass(frozen=True)
class Location:
    """Where a vial is, as a person reads it. Never in a list of a regulated strain."""

    box: StorageUnit
    path: list[str]  # the names from the root down to the box
    row: int
    col: int

    @property
    def label(self) -> str:
        return position_label(self.row, self.col)


def position_label(row: int, col: int) -> str:
    """D6: rows as letters, columns as numbers, both from 1: A1, I9."""
    return f"{chr(ord('A') + row - 1)}{col}"


# Locations of regulated strains (ADR 0009).


def is_regulated(strain: Strain) -> bool:
    """A strain with any active restriction."""
    return regulating_restrictions().filter(strain=strain).exists()


def location_of(vial: Vial) -> Location | None:
    """Where the vial is now. Only for a vial whose strain is not regulated, or inside a reveal."""
    placement = (
        VialPlacement.objects.select_related("box")
        .filter(vial=vial, removed_at__isnull=True)
        .first()
    )
    if placement is None:
        return None
    above = dict(StorageUnit.objects.filter(pk__in=placement.box.path).values_list("pk", "name"))
    return Location(
        box=placement.box,
        path=[above[pk] for pk in placement.box.path],
        row=placement.row,
        col=placement.col,
    )


def vial_reveal_location(*, access: Access, vial: Vial) -> Location | None:
    """The location of a vial of a regulated strain, for a holder of the lab's location grant.

    Under the lab lock the grant and the role are read as committed now. The event (who,
    which vial, which strain, the request) is written and committed before the location is
    returned: a failed write fails the reveal. It holds no location. A vial of a strain
    without restrictions needs no grant and records nothing.
    """
    with audited_atomic():
        lock_lab(vial.lab_id)
        _require(access, vial.lab_id, Perm.VIEW_STRAINS)
        strain = Strain.objects.get(pk=vial.batch.strain_id)
        if is_regulated(strain):
            if not holds_location_grant(lab_id=vial.lab_id, user=access.user):
                raise Forbidden(
                    "Only people the lab's managers named may see where regulated strains are.",
                    code="location_grant_required",
                )
            record_event(
                VIAL_LOCATION_REVEALED,
                Change(VIAL, vial.public_id, {}, lab_id=vial.lab_id, strain_id=strain.public_id),
            )
    # Read after the commit, so nothing is returned that the trail does not show.
    return location_of(vial)

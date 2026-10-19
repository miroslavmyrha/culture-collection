"""Where material is stored: freezers and LN2 tanks, racks in them, boxes in those (ADR 0008, D14).

One table for every level, scoped by lab. KIND_SPEC says which kind may hold
which: freezers and tanks are the roots, a rack sits in a freezer or a tank, a
box in a rack or directly in a freezer or a tank. A box has rows and columns,
copied from its BoxType when it is created; they change only while no
position is occupied (services.box_occupied).

The tree:
- `parent` points at the unit that holds this one (PROTECT: a unit with
  something in it is never removed under it). Units are never deleted:
  a unit that is gone is retired, and keeps its place in the history.
- `path` is the ids of the root, every unit below it and the unit itself.
  Only the database writes it: a trigger computes it from the parent on every
  insert and move, refuses a parent in another lab, a kind the parent may not
  hold and a move under the unit's own subtree, and rewrites the paths of
  every unit below a moved one (migration 0003). Internal ids: it never
  leaves the server.
- `slot` is the position inside the parent where the parent has numbered
  places (a shelf of a freezer, a position in a rack), 1-based. Optional.

Biosafety (ADR 0009): `max_risk_group` caps what may be stored in the unit and
everything in it. Every root states one; a unit below may lower it. The
effective cap is the lowest along the path (selectors, policy.may_store).
"""

from dataclasses import dataclass
from typing import Self

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Exists, F, Func, Min, OuterRef, Q, Subquery
from django.db.models.functions import Upper

from cultures.core.models import PublicModel
from cultures.labs.models import Lab
from cultures.labs.querysets import LabScopedQuerySet

BOX_TYPE_NAME_UNIQUE = "storage_boxtype_name_uniq"
UNIT_NAME_UNIQUE = "storage_unit_name_uniq"
UNIT_SLOT_UNIQUE = "storage_unit_slot_uniq"
UNIT_BARCODE_UNIQUE = "storage_unit_barcode_uniq"

# Rows are labelled with letters (D6: A1, B7), so a box has at most 26 of them. Columns too:
# no box made for cryovials or freeze-dried ampoules is wider.
MAX_ROWS = 26
MAX_COLS = 26
# Degrees Celsius a unit may be set to: from absolute zero to a warm room.
MIN_TEMPERATURE_C = -273
MAX_TEMPERATURE_C = 100
TRIMMED = r"^\S(.*\S)?$"


class UnitKind(models.TextChoices):
    FREEZER = "freezer", "Freezer"
    LN2_TANK = "ln2_tank", "LN2 tank"
    RACK = "rack", "Rack"
    BOX = "box", "Box"


class UnitStatus(models.TextChoices):
    """Active <> out of service, either > retired, which is final. Never deleted."""

    ACTIVE = "active", "Active"
    OUT_OF_SERVICE = "out_of_service", "Out of service"
    RETIRED = "retired", "Retired"


@dataclass(frozen=True)
class KindSpec:
    # The kinds that may hold this one. Empty: a root, held by nothing.
    held_by: frozenset[UnitKind]
    # Rows and columns of positions, copied from a box type.
    grid: bool = False


# Which kind may hold which. The path trigger (migration 0003) refuses the same pairs, and
# tests/test_tree.py tries every pair against both, so the two cannot drift apart.
KIND_SPEC: dict[UnitKind, KindSpec] = {
    UnitKind.FREEZER: KindSpec(held_by=frozenset()),
    UnitKind.LN2_TANK: KindSpec(held_by=frozenset()),
    UnitKind.RACK: KindSpec(held_by=frozenset({UnitKind.FREEZER, UnitKind.LN2_TANK})),
    UnitKind.BOX: KindSpec(
        held_by=frozenset({UnitKind.FREEZER, UnitKind.LN2_TANK, UnitKind.RACK}), grid=True
    ),
}
ROOT_KINDS = sorted(kind for kind, spec in KIND_SPEC.items() if not spec.held_by)


def may_hold(parent: UnitKind, child: UnitKind) -> bool:
    return parent in KIND_SPEC[child].held_by


class BoxType(PublicModel):
    """A box format the collection uses ("81-place cryobox, 9 x 9"). Global, managed by staff.

    Rows and columns never change (a trigger refuses it): boxes copy them when they are
    created, and a type whose size changed would no longer describe its boxes.
    """

    name = models.CharField(max_length=100)
    rows = models.PositiveSmallIntegerField()
    cols = models.PositiveSmallIntegerField()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(Upper("name"), name=BOX_TYPE_NAME_UNIQUE),
            models.CheckConstraint(
                condition=Q(name__regex=TRIMMED), name="storage_boxtype_name_trimmed"
            ),
            models.CheckConstraint(
                condition=Q(rows__gte=1, rows__lte=MAX_ROWS, cols__gte=1, cols__lte=MAX_COLS),
                name="storage_boxtype_size",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.rows} x {self.cols})"


class IsAnyOf(Func):
    """`value = ANY(array)`, a condition. A lookup would wrap the right side in parentheses,
    and `= (ANY(...))` is no SQL."""

    arg_joiner = " = ANY("
    template = "%(expressions)s)"
    output_field = models.BooleanField()


class StorageUnitQuerySet(LabScopedQuerySet["StorageUnit"]):
    def with_path_facts(self) -> Self:
        """Facts of the whole path, one subquery each, never a query per row:
        `effective_max_risk_group`, the lowest cap of the unit and every unit above it, and
        `path_active`, whether all of them are active."""
        on_path = StorageUnit.objects.filter(IsAnyOf(F("pk"), OuterRef("path")))
        lowest = on_path.order_by().values("lab").annotate(cap=Min("max_risk_group")).values("cap")
        return self.annotate(
            effective_max_risk_group=Subquery(lowest[:1]),
            path_active=~Exists(on_path.exclude(status=UnitStatus.ACTIVE)),
        )


class StorageUnit(PublicModel):
    # No index of its own: the unique (lab, barcode) below leads with lab.
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+", db_index=False)
    kind = models.CharField(max_length=20, choices=UnitKind.choices)
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    slot = models.PositiveSmallIntegerField(null=True, blank=True)
    # A label scanned from the unit itself. Null when it has none (never two with the same).
    barcode = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001 (null: none)
    status = models.CharField(max_length=20, choices=UnitStatus.choices, default=UnitStatus.ACTIVE)
    retired_at = models.DateTimeField(null=True, blank=True)
    # Boxes only: the type it was made from, and its size, copied from the type.
    box_type = models.ForeignKey(
        BoxType, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    rows = models.PositiveSmallIntegerField(null=True, blank=True)
    cols = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature_c = models.SmallIntegerField(null=True, blank=True)
    max_risk_group = models.PositiveSmallIntegerField(null=True, blank=True)
    # Written only by the path trigger. The default is what Django sends; the trigger replaces it.
    path = ArrayField(models.BigIntegerField(), default=list, editable=False)

    objects = StorageUnitQuerySet.as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            # Unique among the units of one parent, and among the roots of one lab, ignoring
            # case. A retired unit keeps its name but no longer blocks it. One expression,
            # placed first (django-migration-linter 6.0.0), and a condition without
            # parentheses for the same reason.
            models.UniqueConstraint(
                Upper("name"),
                "lab",
                "parent",
                nulls_distinct=False,
                condition=Q(retired_at__isnull=True),
                name=UNIT_NAME_UNIQUE,
            ),
            models.UniqueConstraint(
                fields=["parent", "slot"],
                condition=Q(retired_at__isnull=True),
                name=UNIT_SLOT_UNIQUE,
            ),
            models.UniqueConstraint(fields=["lab", "barcode"], name=UNIT_BARCODE_UNIQUE),
            models.CheckConstraint(
                condition=Q(kind__in=UnitKind.values), name="storage_unit_kind_valid"
            ),
            models.CheckConstraint(
                condition=Q(status__in=UnitStatus.values), name="storage_unit_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(status=UnitStatus.RETIRED, retired_at__isnull=False)
                | (~Q(status=UnitStatus.RETIRED) & Q(retired_at__isnull=True)),
                name="storage_unit_retired_at_iff_retired",
            ),
            models.CheckConstraint(
                condition=Q(name__regex=TRIMMED), name="storage_unit_name_trimmed"
            ),
            models.CheckConstraint(
                condition=Q(barcode__isnull=True) | Q(barcode__regex=r"^\S+$"),
                name="storage_unit_barcode_no_spaces",
            ),
            # Freezers and tanks are the roots, and only they.
            models.CheckConstraint(
                condition=Q(parent__isnull=True, kind__in=ROOT_KINDS)
                | (Q(parent__isnull=False) & ~Q(kind__in=ROOT_KINDS)),
                name="storage_unit_roots_are_freezers_or_tanks",
            ),
            models.CheckConstraint(
                condition=Q(parent__isnull=False) | Q(slot__isnull=True),
                name="storage_unit_root_has_no_slot",
            ),
            models.CheckConstraint(
                condition=Q(slot__isnull=True) | Q(slot__gte=1), name="storage_unit_slot_positive"
            ),
            # Every path starts at a root with a cap, so the effective cap always exists.
            models.CheckConstraint(
                condition=Q(parent__isnull=False) | Q(max_risk_group__isnull=False),
                name="storage_unit_root_has_max_risk_group",
            ),
            models.CheckConstraint(
                condition=Q(max_risk_group__isnull=True)
                | Q(max_risk_group__gte=1, max_risk_group__lte=4),
                name="storage_unit_max_risk_group_1_to_4",
            ),
            models.CheckConstraint(
                condition=Q(temperature_c__isnull=True)
                | Q(temperature_c__gte=MIN_TEMPERATURE_C, temperature_c__lte=MAX_TEMPERATURE_C),
                name="storage_unit_temperature_range",
            ),
            # isnull=False spelled out: a CHECK passes when its condition is NULL.
            models.CheckConstraint(
                condition=Q(
                    kind=UnitKind.BOX,
                    box_type__isnull=False,
                    rows__isnull=False,
                    cols__isnull=False,
                    rows__gte=1,
                    rows__lte=MAX_ROWS,
                    cols__gte=1,
                    cols__lte=MAX_COLS,
                )
                | (
                    ~Q(kind=UnitKind.BOX)
                    & Q(box_type__isnull=True, rows__isnull=True, cols__isnull=True)
                ),
                name="storage_unit_grid_iff_box",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.name}"

    @property
    def is_retired(self) -> bool:
        return self.status == UnitStatus.RETIRED

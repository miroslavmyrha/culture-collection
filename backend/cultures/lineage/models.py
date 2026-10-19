"""The lineage of a strain's material (ADR 0008, D1): deposit > passage > batch > vial.

A passage has exactly one source: the deposit (the material as received,
passage 0, D3), a parent passage (a subculture), or a vial that was revived.
Each is numbered one more than its source. Passages are never changed or
deleted: a guard trigger holds it (migration 0002). That a source belongs to
the same strain crosses rows: the services check it.

A batch is one preservation of one passage, a vial one physical item of a
batch, used whole (no quantity: stock is a count of rows). Where a vial is, is a
placement: one row per stay in one position of one box, with a start and an end
(D5). The amendment of 2026-10-19 (#16) to ADR 0008 has the states and edges.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Func, Q
from django.db.models.lookups import Exact

from cultures.core.models import PublicModel
from cultures.deposits.models import Deposit
from cultures.labs.models import Lab
from cultures.labs.querysets import LabScopedQuerySet
from cultures.storage.models import StorageUnit
from cultures.strains.models import Strain

BATCH_NUMBER_UNIQUE = "lineage_batch_strain_number_uniq"
VIAL_SEQ_UNIQUE = "lineage_vial_batch_seq_uniq"
VIAL_BARCODE_UNIQUE = "lineage_vial_lab_barcode_uniq"
ONE_OPEN_PLACEMENT = "lineage_placement_one_open_per_vial"
POSITION_TAKEN = "lineage_placement_one_open_per_position"

# A batch is made at the bench in one go: more vials than a box holds are two batches.
MAX_VIALS_PER_BATCH = 200
TRIMMED = r"^\S(.*\S)?$"


class Passage(PublicModel):
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    strain = models.ForeignKey(Strain, on_delete=models.PROTECT, related_name="passages")
    # Counted from receipt: the material as received is 0 (ADR 0008, D3).
    number = models.PositiveIntegerField()
    source_deposit = models.OneToOneField(
        Deposit, on_delete=models.PROTECT, related_name="first_passage", null=True, blank=True
    )
    source_passage = models.ForeignKey(
        "self", on_delete=models.PROTECT, related_name="children", null=True, blank=True
    )
    # A revival: the vial is consumed, and is the source of this one passage only.
    source_vial = models.OneToOneField(
        "Vial", on_delete=models.PROTECT, related_name="revived_as", null=True, blank=True
    )

    objects = LabScopedQuerySet["Passage"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.CheckConstraint(
                condition=Exact(
                    Func(
                        F("source_deposit"),
                        F("source_passage"),
                        F("source_vial"),
                        function="num_nonnulls",
                        output_field=models.IntegerField(),
                    ),
                    1,
                ),
                name="lineage_passage_one_source",
            ),
            models.CheckConstraint(
                condition=Q(source_deposit__isnull=False, number=0)
                | Q(source_deposit__isnull=True, number__gte=1),
                name="lineage_passage_zero_iff_from_deposit",
            ),
        ]

    def __str__(self) -> str:
        return f"passage {self.number} of {self.strain_id}"


class Method(models.TextChoices):
    CRYO_MINUS80 = "cryo_minus80", "Frozen at -80 °C"
    CRYO_LN2 = "cryo_ln2", "Frozen in liquid nitrogen"
    LYOPHILISED = "lyophilised", "Freeze-dried"


class Purpose(models.TextChoices):
    """ADR 0008, D15: the seed stock is never distributed (OECD BRC guidelines, General 11.2)."""

    SEED = "seed", "Seed stock"
    DISTRIBUTION = "distribution", "Distribution stock"


class BatchStatus(models.TextChoices):
    """A batch starts pending its checks. Release and hold come with the checks (#17)."""

    PENDING_CHECK = "pending_check", "Pending check"
    RELEASED = "released", "Released"
    ON_HOLD = "on_hold", "On hold"
    EXHAUSTED = "exhausted", "Exhausted"


class Batch(PublicModel):
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    # No index of its own: the unique (strain, number) below leads with it.
    strain = models.ForeignKey(
        Strain, on_delete=models.PROTECT, related_name="batches", db_index=False
    )
    passage = models.ForeignKey(Passage, on_delete=models.PROTECT, related_name="batches")
    number = models.PositiveIntegerField()
    method = models.CharField(max_length=20, choices=Method.choices)
    # Free text that names no person: "10 % glycerol", or the lyoprotectant ("skim milk").
    cryoprotectant = models.CharField(max_length=100, blank=True)
    preserved_on = models.DateField()  # a Czech day, never in the future (the service)
    vial_count_created = models.PositiveIntegerField()
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    status = models.CharField(
        max_length=20, choices=BatchStatus.choices, default=BatchStatus.PENDING_CHECK
    )

    objects = LabScopedQuerySet["Batch"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(fields=["strain", "number"], name=BATCH_NUMBER_UNIQUE),
            models.CheckConstraint(
                condition=Q(number__gte=1), name="lineage_batch_number_positive"
            ),
            models.CheckConstraint(
                condition=Q(method__in=Method.values), name="lineage_batch_method_valid"
            ),
            models.CheckConstraint(
                condition=Q(purpose__in=Purpose.values), name="lineage_batch_purpose_valid"
            ),
            models.CheckConstraint(
                condition=Q(status__in=BatchStatus.values), name="lineage_batch_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(vial_count_created__gte=1, vial_count_created__lte=MAX_VIALS_PER_BATCH),
                name="lineage_batch_vial_count_range",
            ),
            models.CheckConstraint(
                condition=Q(cryoprotectant="") | Q(cryoprotectant__regex=TRIMMED),
                name="lineage_batch_cryoprotectant_trimmed",
            ),
        ]

    def __str__(self) -> str:
        return f"batch {self.number} of {self.strain_id}"


class VialStatus(models.TextChoices):
    """ADR 0008, D7. The edges are in EDGES below and in the vial trigger (migration 0005)."""

    AVAILABLE = "available", "Available"
    RESERVED = "reserved", "Reserved"
    CONSUMED = "consumed", "Consumed"
    QUARANTINED = "quarantined", "Quarantined"
    TO_DESTROY = "to_destroy", "To destroy"
    DESTROYED = "destroyed", "Destroyed"
    LOST = "lost", "Lost"
    DISTRIBUTED = "distributed", "Distributed"
    ENTERED_IN_ERROR = "entered_in_error", "Entered in error"


S = VialStatus
# Which status may follow which. The vial trigger refuses every other pair, and
# tests/test_vial_states.py tries all 81 against both.
EDGES: dict[VialStatus, frozenset[VialStatus]] = {
    S.AVAILABLE: frozenset(
        {S.RESERVED, S.CONSUMED, S.QUARANTINED, S.TO_DESTROY, S.LOST, S.ENTERED_IN_ERROR}
    ),
    S.RESERVED: frozenset({S.AVAILABLE, S.DISTRIBUTED, S.TO_DESTROY}),
    S.QUARANTINED: frozenset({S.AVAILABLE, S.TO_DESTROY}),
    S.TO_DESTROY: frozenset({S.DESTROYED}),
    S.LOST: frozenset({S.AVAILABLE}),
    S.CONSUMED: frozenset(),
    S.DESTROYED: frozenset(),
    S.DISTRIBUTED: frozenset(),
    S.ENTERED_IN_ERROR: frozenset(),
}
# A vial in one of these is not in a box: its placement is closed with the status as reason.
NOT_IN_A_BOX: frozenset[VialStatus] = frozenset(
    {S.CONSUMED, S.DESTROYED, S.DISTRIBUTED, S.ENTERED_IN_ERROR, S.LOST}
)


class Vial(PublicModel):
    # No index of their own: the unique (lab, barcode) and (batch, seq) lead with them.
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+", db_index=False)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="vials", db_index=False)
    seq = models.PositiveIntegerField()
    # A pre-printed or scanned code (D17). Null when the tube has none (never two the same).
    barcode = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001 (null: none)
    status = models.CharField(
        max_length=20, choices=VialStatus.choices, default=VialStatus.AVAILABLE
    )
    # Null until the first change of status: only such a vial may be entered in error.
    status_changed_at = models.DateTimeField(null=True, blank=True)

    objects = LabScopedQuerySet["Vial"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(fields=["batch", "seq"], name=VIAL_SEQ_UNIQUE),
            models.UniqueConstraint(fields=["lab", "barcode"], name=VIAL_BARCODE_UNIQUE),
            models.CheckConstraint(condition=Q(seq__gte=1), name="lineage_vial_seq_positive"),
            models.CheckConstraint(
                condition=Q(status__in=VialStatus.values), name="lineage_vial_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(barcode__isnull=True) | Q(barcode__regex=r"^\S+$"),
                name="lineage_vial_barcode_no_spaces",
            ),
            models.CheckConstraint(
                condition=Q(status=VialStatus.AVAILABLE) | Q(status_changed_at__isnull=False),
                name="lineage_vial_changed_at_once_changed",
            ),
        ]

    def __str__(self) -> str:
        return f"vial {self.seq} of {self.batch_id}"


class RemovalReason(models.TextChoices):
    MOVED = "moved", "Moved"
    CONSUMED = "consumed", "Consumed"
    DESTROYED = "destroyed", "Destroyed"
    DISTRIBUTED = "distributed", "Distributed"
    LOST = "lost", "Lost"
    ENTERED_IN_ERROR = "entered_in_error", "Entered in error"


class VialPlacement(PublicModel):
    """One stay of a vial in one position (ADR 0008, D5): open while removed_at is null."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    vial = models.ForeignKey(Vial, on_delete=models.PROTECT, related_name="placements")
    # No index of its own: lineage_placement_box_pos_idx leads with it.
    box = models.ForeignKey(
        StorageUnit, on_delete=models.PROTECT, related_name="placements", db_index=False
    )
    row = models.PositiveSmallIntegerField()
    col = models.PositiveSmallIntegerField()
    placed_at = models.DateTimeField()
    placed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    removal_reason = models.CharField(max_length=20, choices=RemovalReason.choices, blank=True)

    objects = LabScopedQuerySet["VialPlacement"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["vial"], condition=Q(removed_at__isnull=True), name=ONE_OPEN_PLACEMENT
            ),
            models.UniqueConstraint(
                fields=["box", "row", "col"],
                condition=Q(removed_at__isnull=True),
                name=POSITION_TAKEN,
            ),
            # The upper bound is the box's size: the service checks it under the box's lock
            # and the placement trigger on insert (migration 0005).
            models.CheckConstraint(
                condition=Q(row__gte=1, col__gte=1), name="lineage_placement_position_positive"
            ),
            models.CheckConstraint(
                condition=Q(
                    removed_at__isnull=True,
                    removed_by__isnull=True,
                    removal_reason="",
                )
                | Q(
                    removed_at__isnull=False,
                    removed_by__isnull=False,
                    removal_reason__in=RemovalReason.values,
                ),
                name="lineage_placement_removal_complete",
            ),
            models.CheckConstraint(
                condition=Q(removed_at__isnull=True) | Q(removed_at__gte=F("placed_at")),
                name="lineage_placement_removed_after_placed",
            ),
        ]
        indexes = [
            models.Index(fields=["box", "row", "col"], name="lineage_placement_box_pos_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.vial_id} in {self.box_id} at {self.row},{self.col}"

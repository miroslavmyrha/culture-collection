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
from cultures.growth.models import GrowthConditions, growth_constraints, medium_index
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


class Passage(PublicModel, GrowthConditions):
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
        indexes = [medium_index("passage_growth_medium_idx")]
        constraints = [
            *PublicModel.Meta.constraints,
            *growth_constraints("lineage_passage"),
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
    """A batch starts pending its checks (ADR 0008, D16, amendment of 2026-10-20)."""

    PENDING_CHECK = "pending_check", "Pending check"
    RELEASED = "released", "Released"
    ON_HOLD = "on_hold", "On hold"
    EXHAUSTED = "exhausted", "Exhausted"


B = BatchStatus
# Which batch status may follow which. The batch trigger (migration 0006) refuses every other
# pair, and tests/test_batch_states.py tries all 16 against both. A curator releases from
# pending_check or on_hold, and holds from pending_check or released. The checks move a batch
# on their own only towards safety: to on_hold when the latest check of a kind failed, and from
# released back to pending_check when a check it was released on is entered in error. Exhausted
# is set by distribution or the last vial leaving (#18).
BATCH_EDGES: dict[BatchStatus, frozenset[BatchStatus]] = {
    B.PENDING_CHECK: frozenset({B.RELEASED, B.ON_HOLD, B.EXHAUSTED}),
    B.RELEASED: frozenset({B.ON_HOLD, B.PENDING_CHECK, B.EXHAUSTED}),
    B.ON_HOLD: frozenset({B.RELEASED, B.EXHAUSTED}),
    B.EXHAUSTED: frozenset(),
}


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
    # Why the batch has its status, from the first change on: the curator's reason for a release
    # or a hold, or the check that moved it. Free text that names no person.
    status_reason = models.TextField(blank=True, db_default="")
    # Null until the first change of status.
    status_changed_at = models.DateTimeField(null=True, blank=True)

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
            # Pending its checks as made, without a reason; every later status has one.
            models.CheckConstraint(
                condition=Q(
                    status=BatchStatus.PENDING_CHECK,
                    status_changed_at__isnull=True,
                    status_reason="",
                )
                | Q(status_changed_at__isnull=False, status_reason__regex=r"\S"),
                name="lineage_batch_status_reason_once_changed",
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


# Checks of a batch (#17, ADR 0008, D16): identity, purity and viability, each an append-only
# row. OECD BRC guidelines, General 10.3, and WFCC guidelines 8.2 to 8.5: identity is confirmed
# after receipt, before and after preservation, at intervals and at dispatch, not viability alone.


class CheckKind(models.TextChoices):
    IDENTITY = "identity", "Identity"
    PURITY = "purity", "Purity"
    VIABILITY = "viability", "Viability"


class CheckStage(models.TextChoices):
    """When in the batch's life the check was made. Receipt is the deposit's check (#12)."""

    AFTER_PRESERVATION = "after_preservation", "After preservation"
    PERIODIC = "periodic", "Periodic"
    BEFORE_DISPATCH = "before_dispatch", "Before dispatch"


class CheckResult(models.TextChoices):
    """Reduced: the culture grows and is pure, but less than expected (fewer colonies, a slower
    start). It counts as passed for a release, and the check says what was seen (a note)."""

    PASS = "pass", "Passed"
    REDUCED = "reduced", "Reduced"
    FAIL = "fail", "Failed"


PASSING: frozenset[CheckResult] = frozenset({CheckResult.PASS, CheckResult.REDUCED})


class CheckMethod(models.TextChoices):
    """A short list per kind (METHODS_BY_KIND), and `other` with the method described."""

    MORPHOLOGY = "morphology", "Colony and cell morphology"
    BIOCHEMICAL = "biochemical", "Biochemical profile"
    MALDI_TOF = "maldi_tof", "MALDI-TOF mass spectrometry"
    SEQUENCING = "sequencing", "Gene sequencing"
    STREAK_PLATE = "streak_plate", "Streak plate"
    MICROSCOPY = "microscopy", "Microscopy"
    GROWTH = "growth", "Growth after revival"
    PLATE_COUNT = "plate_count", "Plate count"
    LIVE_DEAD_STAIN = "live_dead_stain", "Live and dead staining"
    OTHER = "other", "Other"


M = CheckMethod
METHODS_BY_KIND: dict[CheckKind, tuple[CheckMethod, ...]] = {
    CheckKind.IDENTITY: (M.MORPHOLOGY, M.BIOCHEMICAL, M.MALDI_TOF, M.SEQUENCING, M.OTHER),
    CheckKind.PURITY: (M.STREAK_PLATE, M.MICROSCOPY, M.OTHER),
    CheckKind.VIABILITY: (M.GROWTH, M.PLATE_COUNT, M.LIVE_DEAD_STAIN, M.OTHER),
}


class CheckUnit(models.TextChoices):
    CFU_PER_ML = "cfu_per_ml", "CFU/mL"
    PERCENT = "percent", "%"


class CheckStatus(models.TextChoices):
    """A check is never changed or deleted. A wrong one is entered in error with a reason, and
    a correction is a new row that supersedes it."""

    VALID = "valid", "Valid"
    ENTERED_IN_ERROR = "entered_in_error", "Entered in error"


# The largest value: 10^12 CFU/mL is beyond any culture.
CHECK_VALUE_DIGITS, CHECK_VALUE_PLACES = 16, 4
MAX_PERCENT = 100


class BatchCheck(PublicModel):
    """One check of one batch. Rows are only added; the one change a row takes is being entered
    in error (the guard trigger of migration 0006)."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    # No index of its own: lineage_batchcheck_latest_idx leads with it.
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name="checks", db_index=False
    )
    kind = models.CharField(max_length=20, choices=CheckKind.choices)
    stage = models.CharField(max_length=20, choices=CheckStage.choices)
    checked_on = models.DateField()  # a Czech day, not before preservation, not in the future
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    method = models.CharField(max_length=20, choices=CheckMethod.choices)
    # The method in words: required for `other`, else optional ("16S rRNA gene, Sanger").
    method_detail = models.CharField(max_length=200, blank=True)
    result = models.CharField(max_length=20, choices=CheckResult.choices)
    value = models.DecimalField(
        max_digits=CHECK_VALUE_DIGITS, decimal_places=CHECK_VALUE_PLACES, null=True, blank=True
    )
    unit = models.CharField(max_length=20, choices=CheckUnit.choices, blank=True)
    # The vial thawed or opened for the check: consumed by it. One vial may serve the checks of
    # several kinds (one plate shows growth and purity).
    vial = models.ForeignKey(
        Vial, on_delete=models.PROTECT, related_name="checks", null=True, blank=True
    )
    # What was seen, in a sentence: required for a reduced result. Names no person.
    note = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=CheckStatus.choices, default=CheckStatus.VALID)
    # The row this one corrects: that row is entered in error in the same transaction.
    supersedes = models.OneToOneField(
        "self", on_delete=models.PROTECT, related_name="superseded_by", null=True, blank=True
    )
    # Why the row was entered in error, set with that status. Names no person.
    reason = models.TextField(blank=True)

    objects = LabScopedQuerySet["BatchCheck"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.CheckConstraint(
                condition=Q(kind__in=CheckKind.values), name="lineage_batchcheck_kind_valid"
            ),
            models.CheckConstraint(
                condition=Q(stage__in=CheckStage.values), name="lineage_batchcheck_stage_valid"
            ),
            models.CheckConstraint(
                condition=Q(result__in=CheckResult.values),
                name="lineage_batchcheck_result_valid",
            ),
            models.CheckConstraint(
                condition=Q(kind=CheckKind.IDENTITY, method__in=METHODS_BY_KIND[CheckKind.IDENTITY])
                | Q(kind=CheckKind.PURITY, method__in=METHODS_BY_KIND[CheckKind.PURITY])
                | Q(kind=CheckKind.VIABILITY, method__in=METHODS_BY_KIND[CheckKind.VIABILITY]),
                name="lineage_batchcheck_method_of_kind",
            ),
            models.CheckConstraint(
                condition=Q(method_detail="") | Q(method_detail__regex=TRIMMED),
                name="lineage_batchcheck_method_detail_trimmed",
            ),
            models.CheckConstraint(
                condition=~Q(method=CheckMethod.OTHER) | ~Q(method_detail=""),
                name="lineage_batchcheck_other_described",
            ),
            models.CheckConstraint(
                condition=Q(value__isnull=True, unit="")
                | Q(value__isnull=False, value__gte=0, unit__in=CheckUnit.values),
                name="lineage_batchcheck_value_with_unit",
            ),
            # A missing value is lineage_batchcheck_value_with_unit's to refuse.
            models.CheckConstraint(
                condition=~Q(unit=CheckUnit.PERCENT)
                | Q(value__isnull=True)
                | Q(value__isnull=False, value__lte=MAX_PERCENT),
                name="lineage_batchcheck_percent_range",
            ),
            models.CheckConstraint(
                condition=~Q(result=CheckResult.REDUCED) | Q(note__regex=r"\S"),
                name="lineage_batchcheck_reduced_has_note",
            ),
            # Also the only statuses there are: valid, or entered in error with a reason.
            models.CheckConstraint(
                condition=Q(status=CheckStatus.VALID, reason="")
                | Q(status=CheckStatus.ENTERED_IN_ERROR, reason__regex=r"\S"),
                name="lineage_batchcheck_reason_iff_in_error",
            ),
        ]
        indexes = [
            # The latest valid check of each kind of a batch (selectors.latest_checks).
            models.Index(
                fields=["batch", "kind", "-checked_on", "-id"], name="lineage_batchcheck_latest_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} check of {self.batch_id}"

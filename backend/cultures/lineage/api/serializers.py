"""Shapes only: the rules across fields and rows are the services' (lineage.services).

Input never names the lab (it comes from the URL), a number, a status a service decides or a
strain (it comes from the passage). Passages, vials and boxes are referenced by public id
through ScopedRelatedField: an unknown id, a malformed one and one out of scope give the
same error.

A vial's location is in the output only when its strain is not regulated: `location` is null
and `location_masked` true for every reader of a regulated vial, a holder of the location
grant too, who reveals it one vial at a time (ADR 0009, amendment of 2026-10-19).
"""

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.request import Request

from cultures.core.api import ScopedRelatedField
from cultures.labs.access import access_of
from cultures.lineage import selectors
from cultures.lineage.models import (
    CHECK_VALUE_DIGITS,
    CHECK_VALUE_PLACES,
    MAX_VIALS_PER_BATCH,
    Batch,
    BatchCheck,
    BatchStatus,
    CheckKind,
    CheckMethod,
    CheckResult,
    CheckStage,
    CheckStatus,
    CheckUnit,
    Method,
    Passage,
    Purpose,
    Vial,
    VialPlacement,
    VialStatus,
)
from cultures.lineage.services import MANUAL_TARGETS, Location, position_label
from cultures.storage.models import StorageUnit

REASON_HELP = "Why, in a sentence. Stored for good: name no person."
NOTE_HELP = "What was seen, in a sentence. Required for a reduced result. Name no person."


def passages_to_preserve(request: Request) -> QuerySet[Passage]:
    return selectors.passages_to_preserve(access_of(request))


def boxes_to_fill(request: Request) -> QuerySet[StorageUnit]:
    """Boxes of any lab where the caller handles vials: the service keeps the vial's own lab."""
    return selectors.boxes_to_fill(access_of(request))


class PassageOutputSerializer(serializers.ModelSerializer[Passage]):
    strain = serializers.UUIDField(source="strain.public_id", read_only=True)
    source_kind = serializers.SerializerMethodField()
    # The passage it was grown from, for a subculture.
    source_passage = serializers.UUIDField(
        source="source_passage.public_id", read_only=True, allow_null=True, default=None
    )
    # The vial it was revived from, for a revival.
    source_vial = serializers.UUIDField(
        source="source_vial.public_id", read_only=True, allow_null=True, default=None
    )
    # Where it sits in the strain's tree from the deposit (#19): the passage it was grown from,
    # or for a revival the passage the vial's batch was preserved from. Null for passage 0.
    parent = serializers.SerializerMethodField()  # type: ignore[assignment]  # Field.parent
    # The revived vial's label, for a revival.
    source_vial_label = serializers.SerializerMethodField()

    class Meta:
        model = Passage
        fields = (
            "public_id",
            "strain",
            "number",
            "source_kind",
            "source_passage",
            "source_vial",
            "parent",
            "source_vial_label",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_parent(self, passage: Passage) -> str | None:
        if passage.source_passage is not None:
            return str(passage.source_passage.public_id)
        if passage.source_vial is not None:
            return str(passage.source_vial.batch.passage.public_id)
        return None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_source_vial_label(self, passage: Passage) -> str | None:
        vial = passage.source_vial
        if vial is None:
            return None
        return f"{passage.strain.accession_number} / {vial.batch.number} / {vial.seq}"

    @extend_schema_field(serializers.ChoiceField(choices=["deposit", "passage", "vial"]))
    def get_source_kind(self, passage: Passage) -> str:
        if passage.source_deposit_id is not None:
            return "deposit"
        return "passage" if passage.source_passage_id is not None else "vial"


class SubcultureInputSerializer(serializers.Serializer[None]):
    source_passage = ScopedRelatedField(model=Passage, scope=passages_to_preserve)


class LatestChecksSerializer(serializers.Serializer[Batch]):
    """The result of the batch's latest valid check of each kind, null when there is none
    (selectors.batch_list)."""

    identity = serializers.ChoiceField(
        choices=CheckResult.choices, source="latest_identity", allow_null=True
    )
    purity = serializers.ChoiceField(
        choices=CheckResult.choices, source="latest_purity", allow_null=True
    )
    viability = serializers.ChoiceField(
        choices=CheckResult.choices, source="latest_viability", allow_null=True
    )


class BatchOutputSerializer(serializers.ModelSerializer[Batch]):
    strain = serializers.UUIDField(source="strain.public_id", read_only=True)
    passage = serializers.UUIDField(source="passage.public_id", read_only=True)
    passage_number = serializers.IntegerField(source="passage.number", read_only=True)
    method = serializers.ChoiceField(choices=Method.choices, read_only=True)
    purpose = serializers.ChoiceField(choices=Purpose.choices, read_only=True)
    status = serializers.ChoiceField(choices=BatchStatus.choices, read_only=True)
    vials_available = serializers.IntegerField(read_only=True)
    # Available vials that may go out: of a released distribution batch, else 0.
    vials_distributable = serializers.IntegerField(read_only=True)
    latest_checks = LatestChecksSerializer(source="*", read_only=True)

    class Meta:
        model = Batch
        fields = (
            "public_id",
            "strain",
            "number",
            "passage",
            "passage_number",
            "method",
            "cryoprotectant",
            "preserved_on",
            "purpose",
            "status",
            "status_reason",
            "status_changed_at",
            "latest_checks",
            "vial_count_created",
            "vials_available",
            "vials_distributable",
            "created_at",
        )
        read_only_fields = fields


class BatchDecisionInputSerializer(serializers.Serializer[None]):
    """A release or a hold: why, in a sentence."""

    reason = serializers.CharField(help_text=REASON_HELP)


def batches_to_check(request: Request) -> QuerySet[Batch]:
    return selectors.batches_to_check(access_of(request))


def vials_to_check(request: Request) -> QuerySet[Vial]:
    return selectors.vials_to_check(access_of(request))


def checks_to_correct(request: Request) -> QuerySet[BatchCheck]:
    return selectors.checks_to_correct(access_of(request))


class BatchCheckOutputSerializer(serializers.ModelSerializer[BatchCheck]):
    batch = serializers.UUIDField(source="batch.public_id", read_only=True)
    batch_number = serializers.IntegerField(source="batch.number", read_only=True)
    kind = serializers.ChoiceField(choices=CheckKind.choices, read_only=True)
    stage = serializers.ChoiceField(choices=CheckStage.choices, read_only=True)
    method = serializers.ChoiceField(choices=CheckMethod.choices, read_only=True)
    result = serializers.ChoiceField(choices=CheckResult.choices, read_only=True)
    unit = serializers.ChoiceField(choices=CheckUnit.choices, allow_blank=True, read_only=True)
    status = serializers.ChoiceField(choices=CheckStatus.choices, read_only=True)
    # The username of the person who made the check: shown to the lab's members, like the
    # member list. The audit trail holds only the user's id.
    performed_by = serializers.CharField(source="performed_by.username", read_only=True)
    vial = serializers.UUIDField(
        source="vial.public_id", read_only=True, allow_null=True, default=None
    )
    vial_label = serializers.SerializerMethodField()
    supersedes = serializers.UUIDField(
        source="supersedes.public_id", read_only=True, allow_null=True, default=None
    )

    class Meta:
        model = BatchCheck
        fields = (
            "public_id",
            "batch",
            "batch_number",
            "kind",
            "stage",
            "checked_on",
            "performed_by",
            "method",
            "method_detail",
            "result",
            "value",
            "unit",
            "vial",
            "vial_label",
            "note",
            "status",
            "supersedes",
            "reason",
            "created_at",
        )
        read_only_fields = fields

    def get_vial_label(self, check: BatchCheck) -> str | None:
        if check.vial is None:
            return None
        return f"{check.batch.strain.accession_number} / {check.batch.number} / {check.vial.seq}"


class CheckInputSerializer(serializers.Serializer[None]):
    batch = ScopedRelatedField(model=Batch, scope=batches_to_check)
    kind = serializers.ChoiceField(choices=CheckKind.choices)
    stage = serializers.ChoiceField(choices=CheckStage.choices)
    checked_on = serializers.DateField()
    method = serializers.ChoiceField(choices=CheckMethod.choices)
    method_detail = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    result = serializers.ChoiceField(choices=CheckResult.choices)
    value = serializers.DecimalField(
        max_digits=CHECK_VALUE_DIGITS,
        decimal_places=CHECK_VALUE_PLACES,
        required=False,
        allow_null=True,
        default=None,
    )
    unit = serializers.ChoiceField(
        choices=CheckUnit.choices, required=False, allow_null=True, default=None
    )
    vial = ScopedRelatedField(
        model=Vial, scope=vials_to_check, required=False, allow_null=True, default=None
    )
    note = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default="", help_text=NOTE_HELP
    )
    # A correction: the check this one replaces, entered in error with the reason.
    supersedes = ScopedRelatedField(
        model=BatchCheck,
        scope=checks_to_correct,
        required=False,
        allow_null=True,
        default=None,
    )
    reason = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default="", help_text=REASON_HELP
    )


class CheckErrorInputSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(max_length=2000, help_text=REASON_HELP)


class PreserveInputSerializer(serializers.Serializer[None]):
    passage = ScopedRelatedField(model=Passage, scope=passages_to_preserve)
    method = serializers.ChoiceField(choices=Method.choices)
    purpose = serializers.ChoiceField(choices=Purpose.choices)
    cryoprotectant = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )
    preserved_on = serializers.DateField()
    vial_count = serializers.IntegerField(min_value=1, max_value=MAX_VIALS_PER_BATCH)
    box = ScopedRelatedField(
        model=StorageUnit, scope=boxes_to_fill, required=False, allow_null=True, default=None
    )


class LocationSerializer(serializers.Serializer[Location]):
    box = serializers.UUIDField(source="box.public_id")
    box_name = serializers.CharField(source="box.name")
    # The names from the root down to the box: "Freezer A / Rack 1 / Box 1".
    path = serializers.ListField(child=serializers.CharField())
    row = serializers.IntegerField()
    col = serializers.IntegerField()
    # A field named label shadows Field.label for the type checker only: DRF's metaclass takes
    # declared fields off the class.
    label = serializers.CharField()  # type: ignore[assignment]


def _location(placement: VialPlacement, paths: dict[int, list[str]]) -> Location:
    return Location(
        box=placement.box, path=paths[placement.box_id], row=placement.row, col=placement.col
    )


class VialOutputSerializer(serializers.ModelSerializer[Vial]):
    """Context: `paths`, the box paths of the rows shown (selectors.box_paths), and
    `may_reveal`, whether the reader holds the lab's location grant."""

    label = serializers.SerializerMethodField()  # type: ignore[assignment]  # see LocationSerializer
    batch = serializers.UUIDField(source="batch.public_id", read_only=True)
    batch_number = serializers.IntegerField(source="batch.number", read_only=True)
    status = serializers.ChoiceField(choices=VialStatus.choices, read_only=True)
    placed = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    location_masked = serializers.SerializerMethodField()
    can_reveal = serializers.SerializerMethodField()

    class Meta:
        model = Vial
        fields = (
            "public_id",
            "label",
            "batch",
            "batch_number",
            "seq",
            "barcode",
            "status",
            "status_changed_at",
            "placed",
            "location",
            "location_masked",
            "can_reveal",
        )
        read_only_fields = fields

    def get_label(self, vial: Vial) -> str:
        return f"{vial.batch.strain.accession_number} / {vial.batch.number} / {vial.seq}"

    def _open(self, vial: Vial) -> VialPlacement | None:
        found: list[VialPlacement] = vars(vial)["open_placements"]  # the prefetch, at most one
        return found[0] if found else None

    # Whether the vial is in a box: true for a masked one too, a fact the bench sees anyway.
    def get_placed(self, vial: Vial) -> bool:
        return self._open(vial) is not None

    @extend_schema_field(LocationSerializer(allow_null=True))
    def get_location(self, vial: Vial) -> dict[str, Any] | None:
        placement = self._open(vial)
        if vars(vial)["regulated"] or placement is None:
            return None
        return LocationSerializer(_location(placement, self.context["paths"])).data

    def get_location_masked(self, vial: Vial) -> bool:
        return bool(vars(vial)["regulated"]) and self._open(vial) is not None

    def get_can_reveal(self, vial: Vial) -> bool:
        return self.get_location_masked(vial) and bool(self.context.get("may_reveal"))


class PlaceInputSerializer(serializers.Serializer[None]):
    box = ScopedRelatedField(model=StorageUnit, scope=boxes_to_fill)
    row = serializers.IntegerField(min_value=1, max_value=26)
    col = serializers.IntegerField(min_value=1, max_value=26)


MANUAL_CHOICES = [(s.value, s.label) for s in VialStatus if s in MANUAL_TARGETS]


class VialStatusInputSerializer(serializers.Serializer[None]):
    status = serializers.ChoiceField(choices=MANUAL_CHOICES)
    reason = serializers.CharField(help_text=REASON_HELP)


class BarcodeInputSerializer(serializers.Serializer[None]):
    barcode = serializers.CharField(max_length=64, allow_blank=True)


class RevealOutputSerializer(serializers.Serializer[None]):
    location = LocationSerializer(allow_null=True)


# The box grid (#15). A position names its vial only when the vial's strain is not regulated:
# a regulated vial's position says `masked` and nothing else, to every reader, a holder of the
# location grant too (ADR 0009). The grid shows that the position is taken, never by what.


class BoxVialSerializer(serializers.Serializer[Vial]):
    public_id = serializers.UUIDField()
    label = serializers.SerializerMethodField()  # type: ignore[assignment]  # see LocationSerializer
    status = serializers.ChoiceField(choices=VialStatus.choices)
    barcode = serializers.CharField(allow_null=True)
    strain = serializers.UUIDField(source="batch.strain.public_id")
    accession_number = serializers.CharField(source="batch.strain.accession_number")

    def get_label(self, vial: Vial) -> str:
        return f"{vial.batch.strain.accession_number} / {vial.batch.number} / {vial.seq}"


class BoxPositionSerializer(serializers.Serializer[VialPlacement]):
    """One taken position (selectors.box_positions): the vial, or `masked` without it."""

    row = serializers.IntegerField()
    col = serializers.IntegerField()
    label = serializers.SerializerMethodField()  # type: ignore[assignment]
    masked = serializers.SerializerMethodField()
    vial = serializers.SerializerMethodField()

    def get_label(self, placement: VialPlacement) -> str:
        return position_label(placement.row, placement.col)

    def get_masked(self, placement: VialPlacement) -> bool:
        return bool(vars(placement)["regulated"])

    @extend_schema_field(BoxVialSerializer(allow_null=True))
    def get_vial(self, placement: VialPlacement) -> dict[str, Any] | None:
        if vars(placement)["regulated"]:
            return None
        return BoxVialSerializer(placement.vial).data


class BoxOutputSerializer(serializers.ModelSerializer[StorageUnit]):
    """A box in the list: its size, without its positions."""

    rows = serializers.IntegerField(read_only=True)  # a box always has a size
    cols = serializers.IntegerField(read_only=True)

    class Meta:
        model = StorageUnit
        fields: tuple[str, ...] = ("public_id", "name", "rows", "cols")
        read_only_fields: tuple[str, ...] = fields


class BoxGridOutputSerializer(BoxOutputSerializer):
    """A box with every taken position (context `positions`, selectors.box_positions). A
    position missing from the list is empty."""

    positions = serializers.SerializerMethodField()

    class Meta(BoxOutputSerializer.Meta):
        fields = (*BoxOutputSerializer.Meta.fields, "positions")
        read_only_fields = fields

    @extend_schema_field(BoxPositionSerializer(many=True))
    def get_positions(self, box: StorageUnit) -> list[dict[str, Any]]:
        return list(BoxPositionSerializer(self.context["positions"], many=True).data)

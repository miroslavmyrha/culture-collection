"""Shapes only: the rules across fields and rows are the services' (storage.services).

Input never names the lab (it comes from the URL), the path, the status or the
size of a box (copied from its type). Units and box types are referenced by
public id through ScopedRelatedField: an unknown id, a malformed one and one
out of scope give the same error.
"""

from django.db.models import QuerySet
from rest_framework import serializers
from rest_framework.request import Request

from cultures.core.api import ScopedRelatedField
from cultures.labs.access import access_of
from cultures.storage import selectors
from cultures.storage.models import (
    MAX_TEMPERATURE_C,
    MIN_TEMPERATURE_C,
    BoxType,
    StorageUnit,
    UnitKind,
    UnitStatus,
)

# (value, label) pairs: drf-spectacular reads enum overrides as choices, not plain ints.
RISK_GROUPS = [(1, "1"), (2, "2"), (3, "3"), (4, "4")]
REASON_HELP = "Why, in a sentence. Stored for good: name no person."


def units_to_manage(request: Request) -> QuerySet[StorageUnit]:
    return selectors.units_to_manage(access_of(request))


def all_box_types(request: Request) -> QuerySet[BoxType]:
    """Box types are global: any of them may be referenced."""
    return selectors.box_type_list()


class BoxTypeOutputSerializer(serializers.ModelSerializer[BoxType]):
    class Meta:
        model = BoxType
        fields = ("public_id", "name", "rows", "cols")
        read_only_fields = fields


class UnitBriefSerializer(serializers.ModelSerializer[StorageUnit]):
    kind = serializers.ChoiceField(choices=UnitKind.choices, read_only=True)

    class Meta:
        model = StorageUnit
        fields = ("public_id", "kind", "name")
        read_only_fields = fields


class UnitOutputSerializer(serializers.ModelSerializer[StorageUnit]):
    kind = serializers.ChoiceField(choices=UnitKind.choices, read_only=True)
    status = serializers.ChoiceField(choices=UnitStatus.choices, read_only=True)
    # A field named parent shadows Field.parent for the type checker only: DRF's metaclass
    # takes declared fields off the class.
    parent = serializers.UUIDField(source="parent_public_id", read_only=True, allow_null=True)  # type: ignore[assignment]
    box_type = BoxTypeOutputSerializer(read_only=True, allow_null=True)
    max_risk_group = serializers.ChoiceField(choices=RISK_GROUPS, read_only=True, allow_null=True)
    # The lowest cap of the unit and every unit holding it: what it may take (ADR 0009).
    effective_max_risk_group = serializers.ChoiceField(choices=RISK_GROUPS, read_only=True)
    # The unit and every unit holding it are active: only then may anything go in.
    path_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = StorageUnit
        fields: tuple[str, ...] = (
            "public_id",
            "kind",
            "name",
            "parent",
            "slot",
            "barcode",
            "status",
            "box_type",
            "rows",
            "cols",
            "temperature_c",
            "max_risk_group",
            "effective_max_risk_group",
            "path_active",
            "created_at",
            "retired_at",
        )
        read_only_fields: tuple[str, ...] = fields


class ChildOutputSerializer(serializers.ModelSerializer[StorageUnit]):
    kind = serializers.ChoiceField(choices=UnitKind.choices, read_only=True)
    status = serializers.ChoiceField(choices=UnitStatus.choices, read_only=True)

    class Meta:
        model = StorageUnit
        fields = ("public_id", "kind", "name", "slot", "status", "rows", "cols")
        read_only_fields = fields


class UnitDetailOutputSerializer(UnitOutputSerializer):
    # From the root down to the parent: the breadcrumbs.
    ancestors = UnitBriefSerializer(many=True, read_only=True)
    # Not `children`, the reverse relation, which would read the units unordered.
    children = ChildOutputSerializer(source="contents", many=True, read_only=True)

    class Meta(UnitOutputSerializer.Meta):
        fields = (*UnitOutputSerializer.Meta.fields, "ancestors", "children")
        read_only_fields = fields


class UnitFieldsInputSerializer(serializers.Serializer[None]):
    name = serializers.CharField(max_length=100)
    barcode = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    temperature_c = serializers.IntegerField(
        min_value=MIN_TEMPERATURE_C,
        max_value=MAX_TEMPERATURE_C,
        required=False,
        allow_null=True,
        default=None,
    )
    max_risk_group = serializers.ChoiceField(
        choices=RISK_GROUPS, required=False, allow_null=True, default=None
    )
    box_type = ScopedRelatedField(
        model=BoxType, scope=all_box_types, required=False, allow_null=True, default=None
    )


class UnitCreateInputSerializer(UnitFieldsInputSerializer):
    kind = serializers.ChoiceField(choices=UnitKind.choices)
    parent = ScopedRelatedField(  # type: ignore[assignment]  # see UnitOutputSerializer.parent
        model=StorageUnit, scope=units_to_manage, required=False, allow_null=True, default=None
    )
    slot = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)


class UnitMoveInputSerializer(serializers.Serializer[None]):
    parent = ScopedRelatedField(model=StorageUnit, scope=units_to_manage)  # type: ignore[assignment]
    slot = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)


class UnitStatusInputSerializer(serializers.Serializer[None]):
    status = serializers.ChoiceField(choices=UnitStatus.choices)
    reason = serializers.CharField(help_text=REASON_HELP)

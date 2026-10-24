"""Output of Home (#69). Read only: plain serializers over the selectors' dataclasses."""

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from cultures.labs.permissions import Role
from cultures.lineage.models import BatchStatus

from ..activity import DEPOSIT as DEPOSIT_PAGE
from ..activity import LAB, MTA, REQUEST, REQUESTERS, STRAIN, UNIT, Line
from ..selectors import Action, Group, Item, Kind, LabFigures, Target


class WaitingItemSerializer(serializers.Serializer[Item]):
    lab = serializers.SerializerMethodField()
    subject = serializers.CharField()
    reason = serializers.CharField()
    since = serializers.DateField()
    # The last valid day of an expiring permit.
    due = serializers.DateField(allow_null=True)
    target = serializers.ChoiceField(choices=[t.value for t in Target])
    target_id = serializers.UUIDField(allow_null=True)
    # A request only a manager may approve: a line of a regulated strain (ADR 0009).
    needs_manager = serializers.BooleanField()

    @extend_schema_field(OpenApiTypes.UUID)
    def get_lab(self, item: Item) -> str:
        labs: dict[int, str] = self.context["labs"]
        return labs[item.lab_id]


class WaitingGroupSerializer(serializers.Serializer[Group]):
    kind = serializers.ChoiceField(choices=[k.value for k in Kind])
    # How many wait; at most 20 of them are in items, oldest first.
    total = serializers.IntegerField()
    items = WaitingItemSerializer(many=True)


class BatchCountsSerializer(serializers.Serializer[dict[str, int]]):
    pending_check = serializers.IntegerField()
    released = serializers.IntegerField()
    on_hold = serializers.IntegerField()
    exhausted = serializers.IntegerField()

    def to_representation(self, instance: dict[str, int]) -> dict[str, Any]:
        return {status: instance.get(status, 0) for status in BatchStatus.values}


class MyLabSerializer(serializers.Serializer[LabFigures]):
    public_id = serializers.UUIDField(source="lab.public_id")
    name = serializers.CharField(source="lab.name")
    code = serializers.CharField(source="lab.code")
    role = serializers.ChoiceField(choices=Role.choices)
    strains = serializers.IntegerField()
    batches = BatchCountsSerializer()
    vials_available = serializers.IntegerField()
    # In boxes that may take material now: the box and every unit above it active.
    free_positions = serializers.IntegerField()
    # Submitted, approved or awaiting a second person.
    open_requests = serializers.IntegerField()
    # Only for those who decide on them (curators and up), else null.
    requests_to_decide = serializers.IntegerField(allow_null=True)
    deposits_to_check = serializers.IntegerField(allow_null=True)
    actions = serializers.ListField(
        child=serializers.ChoiceField(choices=[a.value for a in Action])
    )


class OverviewSerializer(serializers.Serializer[dict[str, Any]]):
    waiting = WaitingGroupSerializer(many=True)
    labs = MyLabSerializer(many=True)


ACTIVITY_TARGETS = [STRAIN, REQUEST, DEPOSIT_PAGE, UNIT, MTA, LAB, REQUESTERS]


class ActivityLineSerializer(serializers.Serializer[Line]):
    occurred_at = serializers.DateTimeField()
    lab = serializers.UUIDField(source="lab_public_id")
    lab_code = serializers.CharField()
    # "you", or the pseudonymous label the audit trail stores (`user:<public_id>`, a system actor).
    actor = serializers.CharField()
    summary = serializers.CharField()
    target = serializers.ChoiceField(choices=ACTIVITY_TARGETS, allow_null=True)
    target_id = serializers.UUIDField(allow_null=True)


class ActivitySerializer(serializers.Serializer[dict[str, Any]]):
    results = ActivityLineSerializer(many=True)


class HistoryLineSerializer(serializers.Serializer[Line]):
    """One line of a strain's history (#19): a line of Home's activity without the lab, which
    is the strain's."""

    occurred_at = serializers.DateTimeField()
    actor = serializers.CharField()
    summary = serializers.CharField()
    target = serializers.ChoiceField(choices=ACTIVITY_TARGETS, allow_null=True)
    target_id = serializers.UUIDField(allow_null=True)


class HistoryPageSerializer(serializers.Serializer[dict[str, Any]]):
    """A page of the history: `count` is every line the person may read, `results` this page."""

    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = HistoryLineSerializer(many=True)

"""The top bar's search (#76). Read only: plain serializers over the selectors' dataclasses."""

from rest_framework import serializers

from cultures.lineage.api.serializers import LocationSerializer

from ..selectors import LONGEST, Group, Hit, Kind, LabTotal


class SearchInputSerializer(serializers.Serializer[None]):
    # What the person typed or a scanner sent. Fewer than 2 characters, after spaces are
    # folded, finds nothing.
    q = serializers.CharField(max_length=LONGEST, allow_blank=True, trim_whitespace=False)


class SearchHitSerializer(serializers.Serializer[Hit]):
    public_id = serializers.UUIDField()
    lab = serializers.UUIDField(source="lab.public_id")
    lab_code = serializers.CharField(source="lab.code")
    # The accession number, vial label or request number. Null for a deposit whose strain does
    # not exist yet.
    identifier = serializers.CharField(allow_null=True)
    title = serializers.CharField()
    detail = serializers.CharField()
    # The status value of the kind's own model.
    status = serializers.CharField()
    exact = serializers.BooleanField()
    # A vial's strain, an accepted deposit's strain.
    strain = serializers.UUIDField(source="strain_id", allow_null=True)
    # A placed vial of a strain without active restrictions; null otherwise.
    location = LocationSerializer(allow_null=True)
    # A placed vial of a regulated strain: where it is is shown nowhere in search (ADR 0009).
    location_masked = serializers.BooleanField()


class SearchLabTotalSerializer(serializers.Serializer[LabTotal]):
    lab = serializers.UUIDField(source="lab.public_id")
    lab_code = serializers.CharField(source="lab.code")
    total = serializers.IntegerField()


class SearchGroupSerializer(serializers.Serializer[Group]):
    kind = serializers.ChoiceField(choices=[k.value for k in Kind])
    # Every match the person may see; at most 5 of them are in hits, best first.
    total = serializers.IntegerField()
    labs = SearchLabTotalSerializer(many=True)
    hits = SearchHitSerializer(many=True)


class SearchSerializer(serializers.Serializer[dict[str, object]]):
    groups = SearchGroupSerializer(many=True)

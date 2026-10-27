"""Shapes only: the rules across fields and rows are the services' (growth.services).

Growth conditions come out as one object, `growth`, read from the four flat columns of a strain
or a passage (`source="*"`). They go in as the same object. Input never names the lab (it comes
from the URL); a medium is referenced by public id through ScopedRelatedField, scoped to the
lab in the URL: another lab's id, an unknown id and a malformed one give the same error. The
temperature range and the retired medium are the service's to refuse, with the field named.
"""

from django.db.models import QuerySet
from rest_framework import serializers
from rest_framework.request import Request

from cultures.core.api import ScopedRelatedField
from cultures.growth import selectors
from cultures.growth.models import Atmosphere, GrowthMedium
from cultures.labs.access import access_of
from cultures.labs.models import Lab

REASON_HELP = "Why, in a sentence. Stored for good: name no person."
TEMPERATURE_HELP = "Whole degrees Celsius. Alone, a single value; with the high end, a range."


def lab_media(request: Request) -> QuerySet[GrowthMedium]:
    """The lab's media, retired ones too (the service says why a retired one is refused)."""
    lab: Lab = request.parser_context["view"].lab
    return selectors.medium_list(access=access_of(request), lab=lab)


class MediumBriefSerializer(serializers.ModelSerializer[GrowthMedium]):
    class Meta:
        model = GrowthMedium
        fields: tuple[str, ...] = ("public_id", "name", "composition_reference", "retired_at")
        read_only_fields: tuple[str, ...] = fields


class MediumOutputSerializer(MediumBriefSerializer):
    class Meta(MediumBriefSerializer.Meta):
        fields = (*MediumBriefSerializer.Meta.fields, "created_at")
        read_only_fields = fields


class MediumInputSerializer(serializers.Serializer[None]):
    name = serializers.CharField(max_length=100)
    composition_reference = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        default="",
        help_text="Where the recipe is written down, such as a DSMZ medium number.",
    )


class MediumRetireInputSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(max_length=2000, help_text=REASON_HELP)


class GrowthOutputSerializer(serializers.Serializer[None]):
    """Read from a strain or a passage with source="*"."""

    medium = MediumBriefSerializer(source="growth_medium", read_only=True, allow_null=True)
    temperature_low_c = serializers.IntegerField(
        source="growth_temperature_low_c", read_only=True, allow_null=True
    )
    temperature_high_c = serializers.IntegerField(
        source="growth_temperature_high_c", read_only=True, allow_null=True
    )
    atmosphere = serializers.ChoiceField(
        choices=Atmosphere.choices, source="growth_atmosphere", read_only=True, allow_blank=True
    )


class GrowthInputSerializer(serializers.Serializer[None]):
    medium = ScopedRelatedField(
        model=GrowthMedium, scope=lab_media, required=False, allow_null=True, default=None
    )
    temperature_low_c = serializers.IntegerField(
        required=False, allow_null=True, default=None, help_text=TEMPERATURE_HELP
    )
    temperature_high_c = serializers.IntegerField(
        required=False, allow_null=True, default=None, help_text=TEMPERATURE_HELP
    )
    atmosphere = serializers.ChoiceField(
        choices=Atmosphere.choices, required=False, allow_blank=True, default=""
    )


class StrainGrowthInputSerializer(GrowthInputSerializer):
    reason = serializers.CharField(max_length=2000, help_text=REASON_HELP)

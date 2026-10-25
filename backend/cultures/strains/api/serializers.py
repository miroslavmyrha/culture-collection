"""Shapes only: the rules across fields and rows are the services' (strains.services).

Input never names the lab (it comes from the URL), the accession number, the
status or anything the service decides. A taxon is referenced by its public id
through ScopedRelatedField: an unknown id and a malformed one give the same
error.
"""

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.request import Request

from cultures.biosafety.models import RestrictionKind
from cultures.core.api import ScopedRelatedField
from cultures.strains.countries import COUNTRY_CODES
from cultures.strains.models import (
    Pathogenicity,
    RestrictionEndProposal,
    Strain,
    StrainIdentification,
    StrainRestriction,
    StrainStatus,
)
from cultures.taxonomy.api.serializers import TaxonBriefSerializer
from cultures.taxonomy.models import Taxon

# (value, label) pairs: drf-spectacular reads enum overrides as choices, not plain ints.
RISK_GROUPS = [(1, "1"), (2, "2"), (3, "3"), (4, "4")]
COUNTRY_CHOICES = sorted(COUNTRY_CODES)
REASON_HELP = "Why, in a sentence. Stored for good: name no person."


def all_taxa(request: Request) -> QuerySet[Taxon]:
    """Taxa are global (ADR 0008, D4): any of them may be referenced."""
    return Taxon.objects.all()


class RestrictionBriefSerializer(serializers.ModelSerializer[StrainRestriction]):
    class Meta:
        model = StrainRestriction
        fields = ("kind", "reference")
        read_only_fields = fields


class StrainListOutputSerializer(serializers.ModelSerializer[Strain]):
    taxon = TaxonBriefSerializer(read_only=True)
    risk_group = serializers.ChoiceField(choices=RISK_GROUPS, read_only=True)
    status = serializers.ChoiceField(choices=StrainStatus.choices, read_only=True)
    restrictions = RestrictionBriefSerializer(
        source="active_restrictions", many=True, read_only=True
    )

    class Meta:
        model = Strain
        fields: tuple[str, ...] = (
            "public_id",
            "accession_number",
            "name_as_received",
            "taxon",
            "risk_group",
            "status",
            "restrictions",
            "created_at",
        )
        read_only_fields: tuple[str, ...] = fields


class IdentificationOutputSerializer(serializers.ModelSerializer[StrainIdentification]):
    taxon = TaxonBriefSerializer(read_only=True)

    class Meta:
        model = StrainIdentification
        fields = (
            "public_id",
            "taxon",
            "identified_on",
            "method",
            "reason",
            "is_current",
            "created_at",
        )
        read_only_fields = fields


class EndProposalOutputSerializer(serializers.ModelSerializer[RestrictionEndProposal]):
    """The open proposal to end a restriction (#105). It names nobody: `confirm_refusal` says
    the caller proposed it and so may not confirm it (ADR 0009); null when they may, as far as
    identity goes (confirming is a manager's, strains.confirm_restriction_end)."""

    confirm_refusal = serializers.SerializerMethodField()

    class Meta:
        model = RestrictionEndProposal
        fields = ("public_id", "reason", "proposed_at", "confirm_refusal")
        read_only_fields = fields

    @extend_schema_field(
        serializers.ChoiceField(choices=["confirm_own_end_proposal"], allow_null=True)
    )
    def get_confirm_refusal(self, proposal: RestrictionEndProposal) -> str | None:
        request: Request | None = self.context.get("request")
        user_id = getattr(getattr(request, "user", None), "pk", None)
        return "confirm_own_end_proposal" if proposal.proposed_by_id == user_id else None


class RestrictionOutputSerializer(serializers.ModelSerializer[StrainRestriction]):
    kind = serializers.ChoiceField(choices=RestrictionKind.choices, read_only=True)
    gmo_category = serializers.IntegerField(read_only=True, allow_null=True)
    end_proposal = serializers.SerializerMethodField()

    class Meta:
        model = StrainRestriction
        fields = (
            "public_id",
            "kind",
            "reference",
            "act",
            "gmo_category",
            "created_at",
            "ended_at",
            "end_reason",
            "end_proposal",
        )
        read_only_fields = fields

    @extend_schema_field(EndProposalOutputSerializer(allow_null=True))
    def get_end_proposal(self, restriction: StrainRestriction) -> dict[str, object] | None:
        # strains.selectors.strain_detail prefetches the open one; an ended restriction has none.
        open_ones: list[RestrictionEndProposal] = vars(restriction).get("open_end_proposals", [])
        if not open_ones:
            return None
        return EndProposalOutputSerializer(open_ones[0], context=self.context).data


class StrainDetailOutputSerializer(StrainListOutputSerializer):
    animal_pathogenicity = serializers.ChoiceField(choices=Pathogenicity.choices, read_only=True)
    plant_pathogenicity = serializers.ChoiceField(choices=Pathogenicity.choices, read_only=True)
    identifications = IdentificationOutputSerializer(many=True, read_only=True)
    restriction_history = RestrictionOutputSerializer(
        source="all_restrictions", many=True, read_only=True
    )

    class Meta(StrainListOutputSerializer.Meta):
        fields = (
            *StrainListOutputSerializer.Meta.fields,
            "animal_pathogenicity",
            "plant_pathogenicity",
            "isolation_source",
            "country_of_origin",
            "isolation_date",
            "identifications",
            "restriction_history",
        )
        read_only_fields = fields


class RestrictionInputSerializer(serializers.Serializer[None]):
    kind = serializers.ChoiceField(choices=RestrictionKind.choices)
    reference = serializers.CharField(max_length=100)
    act = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    gmo_category = serializers.IntegerField(
        min_value=1, max_value=4, required=False, allow_null=True, default=None
    )


class StrainFactsInputSerializer(serializers.Serializer[None]):
    """What a check of a deposit found: everything a new strain needs but its name as
    received, which the deposit holds (deposits.services.deposit_accept)."""

    taxon = ScopedRelatedField(model=Taxon, scope=all_taxa)
    identified_on = serializers.DateField()
    identification_method = serializers.CharField(max_length=200)
    risk_group = serializers.ChoiceField(choices=RISK_GROUPS)
    animal_pathogenicity = serializers.ChoiceField(
        choices=Pathogenicity.choices, default=Pathogenicity.UNKNOWN
    )
    plant_pathogenicity = serializers.ChoiceField(
        choices=Pathogenicity.choices, default=Pathogenicity.UNKNOWN
    )
    isolation_source = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    country_of_origin = serializers.ChoiceField(
        choices=COUNTRY_CHOICES, required=False, allow_blank=True, default=""
    )
    isolation_date = serializers.CharField(
        max_length=10, required=False, allow_blank=True, default=""
    )
    # max_length on a many=True serializer is DRF's (ListSerializer, 3.14+); the stubs lack it.
    restrictions = RestrictionInputSerializer(  # type: ignore[call-arg]
        many=True, required=False, default=list, max_length=10
    )


class ReclassifyInputSerializer(serializers.Serializer[None]):
    taxon = ScopedRelatedField(model=Taxon, scope=all_taxa)
    identified_on = serializers.DateField()
    method = serializers.CharField(max_length=200)
    reason = serializers.CharField(help_text=REASON_HELP)


class RiskGroupInputSerializer(serializers.Serializer[None]):
    risk_group = serializers.ChoiceField(choices=RISK_GROUPS)
    reason = serializers.CharField(help_text=REASON_HELP)


class RestrictionAddInputSerializer(RestrictionInputSerializer):
    reason = serializers.CharField(help_text=REASON_HELP)


class EndProposeInputSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(max_length=2000, help_text=REASON_HELP)


class EndConfirmInputSerializer(serializers.Serializer[None]):
    proposal = serializers.UUIDField(help_text="The public id of the proposal the manager read.")


class EndWithdrawInputSerializer(EndConfirmInputSerializer):
    reason = serializers.CharField(max_length=2000, help_text=REASON_HELP)

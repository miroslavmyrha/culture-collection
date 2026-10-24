"""Shapes only: the rules across fields and rows are the services' (deposits.services).

Input never names the lab (it comes from the URL), the status, a version or the
strain. Depositors and MTA templates are referenced by public id through
ScopedRelatedField, scoped to the lab in the URL: another lab's id, an unknown
id and a malformed one give the same error.
"""

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.request import Request

from cultures.core.api import ScopedRelatedField
from cultures.deposits import selectors
from cultures.deposits.models import (
    AbsScope,
    Condition,
    Decision,
    Deposit,
    Depositor,
    DepositStatus,
    DepositTerms,
    MtaTemplate,
    TermsUse,
    Use,
)
from cultures.labs.access import access_of
from cultures.labs.models import Lab
from cultures.strains.api.serializers import COUNTRY_CHOICES, REASON_HELP
from cultures.strains.models import Strain

NOTE_HELP = "About the material. Stored for good: name no person."


def _lab(request: Request) -> Lab:
    """The lab of the URL, as the view resolved it (the view's cached lab, no second query)."""
    lab: Lab = request.parser_context["view"].lab
    return lab


def lab_depositors(request: Request) -> QuerySet[Depositor]:
    return selectors.depositor_list(access=access_of(request), lab=_lab(request))


def lab_mta_templates(request: Request) -> QuerySet[MtaTemplate]:
    return selectors.mta_template_list(access=access_of(request), lab=_lab(request))


class DepositorBriefSerializer(serializers.ModelSerializer[Depositor]):
    name = serializers.CharField(source="contact.name", read_only=True)
    erased = serializers.SerializerMethodField()

    class Meta:
        model = Depositor
        fields: tuple[str, ...] = ("public_id", "name", "institution", "erased")
        read_only_fields: tuple[str, ...] = fields

    def get_erased(self, depositor: Depositor) -> bool:
        return depositor.contact.erased_at is not None


class DepositorOutputSerializer(DepositorBriefSerializer):
    email = serializers.CharField(source="contact.email", read_only=True)
    postal_address = serializers.CharField(source="contact.postal_address", read_only=True)

    class Meta(DepositorBriefSerializer.Meta):
        fields = (*DepositorBriefSerializer.Meta.fields, "email", "postal_address", "created_at")
        read_only_fields = fields


class DepositorInputSerializer(serializers.Serializer[None]):
    name = serializers.CharField(max_length=200)
    email = serializers.EmailField(max_length=254, required=False, allow_blank=True, default="")
    postal_address = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, default=""
    )
    institution = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )


class MtaTemplateBriefSerializer(serializers.ModelSerializer[MtaTemplate]):
    class Meta:
        model = MtaTemplate
        fields: tuple[str, ...] = ("public_id", "code", "version", "title", "text_sha256")
        read_only_fields: tuple[str, ...] = fields


class MtaTemplateListOutputSerializer(MtaTemplateBriefSerializer):
    class Meta(MtaTemplateBriefSerializer.Meta):
        fields = (*MtaTemplateBriefSerializer.Meta.fields, "created_at")
        read_only_fields = fields


class MtaTemplateDetailOutputSerializer(MtaTemplateListOutputSerializer):
    class Meta(MtaTemplateListOutputSerializer.Meta):
        fields = (*MtaTemplateListOutputSerializer.Meta.fields, "text")
        read_only_fields = fields


class MtaTemplateInputSerializer(serializers.Serializer[None]):
    code = serializers.CharField(max_length=20)
    title = serializers.CharField(max_length=200)
    text = serializers.CharField(max_length=100_000, trim_whitespace=False)


class TermsUseSerializer(serializers.ModelSerializer[TermsUse]):
    use = serializers.ChoiceField(choices=Use.choices)
    decision = serializers.ChoiceField(choices=Decision.choices)

    class Meta:
        model = TermsUse
        fields = ("use", "decision")


class TermsOutputSerializer(serializers.ModelSerializer[DepositTerms]):
    mta = MtaTemplateBriefSerializer(read_only=True, allow_null=True)
    abs_scope = serializers.ChoiceField(choices=AbsScope.choices, read_only=True)
    mat_uses = serializers.ListField(
        child=serializers.ChoiceField(choices=Use.choices), read_only=True
    )
    uses = TermsUseSerializer(many=True, read_only=True)

    class Meta:
        model = DepositTerms
        fields = (
            "public_id",
            "version",
            "is_active",
            "mta",
            "abs_scope",
            "country_of_origin",
            "collection_date",
            "pic_reference",
            "mat_reference",
            "ircc",
            "permit_reference",
            "mat_uses",
            "reason",
            "uses",
            "created_at",
        )
        read_only_fields = fields


class StrainTermsOutputSerializer(serializers.Serializer[dict[str, Any]]):
    """A strain's terms of use (#19): every version, newest first, at most one active."""

    # The deposit they belong to, for a reader who may open it (deposits.view), else null.
    deposit = serializers.UUIDField(allow_null=True)
    versions = TermsOutputSerializer(many=True)


class StrainBriefSerializer(serializers.ModelSerializer[Strain]):
    class Meta:
        model = Strain
        fields = ("public_id", "accession_number")
        read_only_fields = fields


class DepositListOutputSerializer(serializers.ModelSerializer[Deposit]):
    status = serializers.ChoiceField(choices=DepositStatus.choices, read_only=True)
    depositor = DepositorBriefSerializer(read_only=True)
    strain = StrainBriefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Deposit
        fields: tuple[str, ...] = (
            "public_id",
            "status",
            "received_on",
            "name_as_received",
            "depositor",
            "strain",
            "created_at",
        )
        read_only_fields: tuple[str, ...] = fields


class DepositDetailOutputSerializer(DepositListOutputSerializer):
    condition = serializers.ChoiceField(choices=Condition.choices, read_only=True)
    terms = serializers.SerializerMethodField()
    terms_history = TermsOutputSerializer(many=True, read_only=True)

    class Meta(DepositListOutputSerializer.Meta):
        fields = (
            *DepositListOutputSerializer.Meta.fields,
            "condition",
            "condition_note",
            "depositor_passages",
            "decided_at",
            "rejection_reason",
            "terms",
            "terms_history",
        )
        read_only_fields = fields

    @extend_schema_field(TermsOutputSerializer)
    def get_terms(self, deposit: Deposit) -> dict[str, Any]:
        """The active version: the first of the prefetched history (newest first)."""
        history: list[DepositTerms] = vars(deposit)["terms_history"]
        active = next(t for t in history if t.is_active)
        return TermsOutputSerializer(active).data


class TermsInputSerializer(serializers.Serializer[None]):
    mta = ScopedRelatedField(model=MtaTemplate, scope=lab_mta_templates, allow_null=True)
    abs_scope = serializers.ChoiceField(choices=AbsScope.choices)
    country_of_origin = serializers.ChoiceField(
        choices=COUNTRY_CHOICES, required=False, allow_blank=True, default=""
    )
    collection_date = serializers.CharField(
        max_length=10, required=False, allow_blank=True, default=""
    )
    pic_reference = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    mat_reference = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    ircc = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    permit_reference = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    # The uses by a subsequent user the MAT covers: in scope only.
    mat_uses = serializers.ListField(
        child=serializers.ChoiceField(choices=Use.choices),
        required=False,
        default=list,
        max_length=len(Use.values),
    )
    # max_length on a many=True serializer is DRF's (ListSerializer, 3.14+); the stubs lack it.
    uses = TermsUseSerializer(many=True, max_length=20)  # type: ignore[call-arg]


class DepositReceiveInputSerializer(serializers.Serializer[None]):
    depositor = ScopedRelatedField(model=Depositor, scope=lab_depositors)
    received_on = serializers.DateField()
    condition = serializers.ChoiceField(choices=Condition.choices)
    condition_note = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default="", help_text=NOTE_HELP
    )
    name_as_received = serializers.CharField(max_length=200)
    depositor_passages = serializers.IntegerField(
        min_value=0, max_value=10_000, required=False, allow_null=True, default=None
    )
    terms = TermsInputSerializer()


class TermsReplaceInputSerializer(serializers.Serializer[None]):
    terms = TermsInputSerializer()
    reason = serializers.CharField(max_length=2000, help_text=REASON_HELP)


class RejectInputSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(max_length=2000, help_text=REASON_HELP)

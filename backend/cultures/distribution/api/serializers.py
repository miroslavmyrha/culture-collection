"""Shapes only: the rules across fields and rows are the services' and the policy's.

Input never names the lab (it comes from the URL), a status, a number, the destination (copied
from the requester), the terms or the MTA version of a line (pinned by the service). Requesters,
strains and MTA versions are referenced by public id through ScopedRelatedField, scoped to the
lab in the URL: another lab's id, an unknown id and a malformed one give the same error.

A request's detail is read by viewers too: it names the requester's institution, never a person.
The signer of an MTA acceptance and the documents reach a person, so they are serialised only
for a caller who may view requesters (`show_people` in the context).
"""

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.request import Request

from cultures.biosafety.policy import permit_today
from cultures.core.api import ScopedRelatedField
from cultures.deposits.models import MtaTemplate, Use
from cultures.distribution import selectors
from cultures.distribution.models import (
    MAX_VIALS_PER_LINE,
    DistributionRequest,
    Document,
    DocumentType,
    LegalForm,
    MtaAcceptance,
    PermitKind,
    RecipientPermit,
    Requester,
    RequestLine,
    RequestStatus,
    SignerRole,
)
from cultures.distribution.policy import Severity
from cultures.labs.access import access_of
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.strains.api.serializers import COUNTRY_CHOICES, REASON_HELP
from cultures.strains.models import Strain

TEXT_HELP = "Stored for good: name no person."


def _lab(request: Request) -> Lab:
    """The lab of the URL, as the view resolved it (the view's cached lab, no second query)."""
    lab: Lab = request.parser_context["view"].lab
    return lab


def lab_requesters(request: Request) -> QuerySet[Requester]:
    return selectors.requesters_to_use(access_of(request)).filter(lab=_lab(request))


def lab_strains(request: Request) -> QuerySet[Strain]:
    return Strain.objects.for_access(access_of(request), Perm.MANAGE_DISTRIBUTION).filter(
        lab=_lab(request)
    )


def lab_mtas(request: Request) -> QuerySet[MtaTemplate]:
    return MtaTemplate.objects.for_access(access_of(request), Perm.MANAGE_DISTRIBUTION).filter(
        lab=_lab(request)
    )


class DocumentOutputSerializer(serializers.ModelSerializer[Document]):
    content_type = serializers.ChoiceField(choices=DocumentType.choices, read_only=True)

    class Meta:
        model = Document
        fields = ("public_id", "content_type", "size_bytes", "sha256", "created_at")
        read_only_fields = fields


class PermitOutputSerializer(serializers.ModelSerializer[RecipientPermit]):
    requester = serializers.UUIDField(source="requester.public_id", read_only=True)
    kind = serializers.ChoiceField(choices=PermitKind.choices, read_only=True)
    document = DocumentOutputSerializer(read_only=True)
    valid_today = serializers.SerializerMethodField()

    class Meta:
        model = RecipientPermit
        fields = (
            "public_id",
            "requester",
            "kind",
            "issuer",
            "issuer_country",
            "reference",
            "valid_from",
            "expires_on",
            "covers",
            "quantity_allowed",
            "sendings_allowed",
            "endorsement_reference",
            "endorsed_on",
            "gmo_category",
            "risk_group",
            "document",
            "ended_on",
            "end_reason",
            "valid_today",
            "created_at",
        )
        read_only_fields = fields

    def get_valid_today(self, permit: RecipientPermit) -> bool:
        """Valid on today's Czech day: started, not expired, not ended."""
        today = permit_today()
        return (
            permit.valid_from <= today
            and (permit.expires_on is None or permit.expires_on >= today)
            and (permit.ended_on is None or permit.ended_on > today)
        )


class RequesterOutputSerializer(serializers.ModelSerializer[Requester]):
    legal_form = serializers.ChoiceField(choices=LegalForm.choices, read_only=True)
    name = serializers.CharField(source="contact.name", read_only=True)
    email = serializers.CharField(source="contact.email", read_only=True)
    postal_address = serializers.CharField(source="contact.postal_address", read_only=True)
    erased = serializers.SerializerMethodField()
    permits = PermitOutputSerializer(source="permit_list", many=True, read_only=True)

    class Meta:
        model = Requester
        fields = (
            "public_id",
            "institution",
            "legal_form",
            "registration_number",
            "country",
            "lab_evidence",
            "lab_confirmed_on",
            "name",
            "email",
            "postal_address",
            "erased",
            "permits",
            "created_at",
        )
        read_only_fields = fields

    def get_erased(self, requester: Requester) -> bool:
        return requester.contact.erased_at is not None


class RequesterInputSerializer(serializers.Serializer[None]):
    institution = serializers.CharField(max_length=200)
    legal_form = serializers.ChoiceField(choices=LegalForm.choices)
    registration_number = serializers.CharField(
        max_length=40, required=False, allow_blank=True, default=""
    )
    country = serializers.ChoiceField(choices=COUNTRY_CHOICES)
    lab_evidence = serializers.CharField(max_length=2000, help_text=TEXT_HELP)
    lab_confirmed_on = serializers.DateField()
    # The responsible scientist, and the laboratory's delivery address.
    name = serializers.CharField(max_length=200)
    email = serializers.EmailField(max_length=254, required=False, allow_blank=True, default="")
    postal_address = serializers.CharField(max_length=1000)


class PermitInputSerializer(serializers.Serializer[None]):
    """Sent as multipart/form-data with the file."""

    requester = ScopedRelatedField(model=Requester, scope=lab_requesters)
    kind = serializers.ChoiceField(choices=PermitKind.choices)
    issuer = serializers.CharField(max_length=200)
    issuer_country = serializers.ChoiceField(choices=COUNTRY_CHOICES)
    reference = serializers.CharField(max_length=200)
    valid_from = serializers.DateField()
    expires_on = serializers.DateField(required=False, allow_null=True, default=None)
    covers = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    quantity_allowed = serializers.IntegerField(
        min_value=1, max_value=100_000, required=False, allow_null=True, default=None
    )
    sendings_allowed = serializers.IntegerField(
        min_value=1, max_value=1000, required=False, allow_null=True, default=None
    )
    endorsement_reference = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    endorsed_on = serializers.DateField(required=False, allow_null=True, default=None)
    gmo_category = serializers.IntegerField(
        min_value=1, max_value=4, required=False, allow_null=True, default=None
    )
    risk_group = serializers.IntegerField(
        min_value=1, max_value=4, required=False, allow_null=True, default=None
    )
    file = serializers.FileField(allow_empty_file=False)


class PermitEndInputSerializer(serializers.Serializer[None]):
    ended_on = serializers.DateField()
    reason = serializers.CharField(max_length=2000, help_text=REASON_HELP)


class RequesterBriefSerializer(serializers.ModelSerializer[Requester]):
    class Meta:
        model = Requester
        fields = ("public_id", "institution", "country")
        read_only_fields = fields


class RequestListOutputSerializer(serializers.ModelSerializer[DistributionRequest]):
    number = serializers.CharField(source="label", read_only=True)
    requester = RequesterBriefSerializer(read_only=True)
    status = serializers.ChoiceField(choices=RequestStatus.choices, read_only=True)
    use = serializers.ChoiceField(choices=Use.choices, read_only=True)
    line_count = serializers.IntegerField(read_only=True)
    vial_count = serializers.IntegerField(read_only=True)
    regulated = serializers.BooleanField(read_only=True)

    class Meta:
        model = DistributionRequest
        fields: tuple[str, ...] = (
            "public_id",
            "number",
            "requester",
            "destination_country",
            "use",
            "status",
            "line_count",
            "vial_count",
            "regulated",
            "created_at",
            "decided_at",
        )
        read_only_fields: tuple[str, ...] = fields


class LineStrainSerializer(serializers.ModelSerializer[Strain]):
    taxon = serializers.CharField(source="taxon.name", read_only=True)

    class Meta:
        model = Strain
        fields = ("public_id", "accession_number", "taxon", "risk_group")
        read_only_fields = fields


class MtaBriefSerializer(serializers.ModelSerializer[MtaTemplate]):
    class Meta:
        model = MtaTemplate
        fields = ("public_id", "code", "version", "title")
        read_only_fields = fields


class ReservedVialSerializer(serializers.Serializer[None]):
    """A reserved vial by its label only, never its place (ADR 0009)."""

    public_id = serializers.UUIDField(source="vial.public_id")
    label = serializers.SerializerMethodField()  # type: ignore[assignment]  # shadows Field.label

    def get_label(self, reservation: Any) -> str:
        vial = reservation.vial
        return f"{vial.batch.strain.accession_number} / {vial.batch.number} / {vial.seq}"


class ApprovedPermitSerializer(serializers.Serializer[None]):
    public_id = serializers.UUIDField(source="permit.public_id")
    kind = serializers.ChoiceField(source="permit.kind", choices=PermitKind.choices)
    reference = serializers.CharField(source="permit.reference")


class LineOutputSerializer(serializers.ModelSerializer[RequestLine]):
    strain = LineStrainSerializer(read_only=True)
    terms_version = serializers.IntegerField(source="terms.version", read_only=True)
    mta = MtaBriefSerializer(read_only=True, allow_null=True)
    reserved = ReservedVialSerializer(source="open_reservations", many=True, read_only=True)
    permits = ApprovedPermitSerializer(source="approved_permits", many=True, read_only=True)

    class Meta:
        model = RequestLine
        fields = (
            "public_id",
            "strain",
            "quantity",
            "terms_version",
            "mta",
            "reserved",
            "permits",
        )
        read_only_fields = fields


class AcceptanceOutputSerializer(serializers.ModelSerializer[MtaAcceptance]):
    mta = MtaBriefSerializer(read_only=True)
    signer_role = serializers.ChoiceField(choices=SignerRole.choices, read_only=True)
    signer_name = serializers.SerializerMethodField()
    document = serializers.SerializerMethodField()

    class Meta:
        model = MtaAcceptance
        fields = (
            "public_id",
            "mta",
            "signer_name",
            "signer_role",
            "authorised_signatory",
            "accepted_on",
            "document",
            "created_at",
        )
        read_only_fields = fields

    def _people(self) -> bool:
        return bool(self.context.get("show_people"))

    def get_signer_name(self, acceptance: MtaAcceptance) -> str | None:
        """Null for a caller who may not see people; empty once the signer was erased."""
        return acceptance.signer.name if self._people() else None

    @extend_schema_field(DocumentOutputSerializer(allow_null=True))
    def get_document(self, acceptance: MtaAcceptance) -> dict[str, Any] | None:
        if not self._people():
            return None
        return dict(DocumentOutputSerializer(acceptance.document).data)


class FindingSerializer(serializers.Serializer[None]):
    code = serializers.CharField()
    severity = serializers.ChoiceField(choices=[(s.value, s.value) for s in Severity])
    sentence = serializers.CharField()
    line = serializers.UUIDField(allow_null=True)


class RequestDetailOutputSerializer(RequestListOutputSerializer):
    lines = LineOutputSerializer(source="line_list", many=True, read_only=True)
    acceptances = AcceptanceOutputSerializer(source="acceptance_list", many=True, read_only=True)
    submitted_by = serializers.CharField(source="submitted_by.username", read_only=True)
    decided_by = serializers.CharField(
        source="decided_by.username", read_only=True, allow_null=True
    )
    cancelled_by = serializers.CharField(
        source="cancelled_by.username", read_only=True, allow_null=True
    )
    findings = serializers.SerializerMethodField()

    class Meta(RequestListOutputSerializer.Meta):
        fields = (
            *RequestListOutputSerializer.Meta.fields,
            "end_use",
            "containment_level",
            "submitted_by",
            "decided_by",
            "decision_reason",
            "cancelled_by",
            "cancelled_at",
            "cancel_reason",
            "lines",
            "acceptances",
            "findings",
        )
        read_only_fields = fields

    @extend_schema_field(FindingSerializer(many=True))
    def get_findings(self, request: DistributionRequest) -> list[dict[str, Any]]:
        """What the policy finds today, while the request waits for a decision; else none."""
        findings = self.context.get("findings") or []
        return [
            {
                "code": f.code,
                "severity": f.severity.value,
                "sentence": f.sentence,
                "line": None if f.line is None else f.line.public_id,
            }
            for f in findings
        ]


class LineInputSerializer(serializers.Serializer[None]):
    strain = ScopedRelatedField(model=Strain, scope=lab_strains)
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_VIALS_PER_LINE)


class RequestInputSerializer(serializers.Serializer[None]):
    requester = ScopedRelatedField(model=Requester, scope=lab_requesters)
    use = serializers.ChoiceField(choices=Use.choices)
    end_use = serializers.CharField(max_length=2000, help_text=TEXT_HELP)
    containment_level = serializers.IntegerField(min_value=1, max_value=4)
    # max_length on a many=True serializer is DRF's (ListSerializer, 3.14+); the stubs lack it.
    lines = LineInputSerializer(many=True, max_length=20)  # type: ignore[call-arg]


class ApproveInputSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default="", help_text=REASON_HELP
    )


class ReasonInputSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(max_length=2000, help_text=REASON_HELP)


class AcceptanceInputSerializer(serializers.Serializer[None]):
    """Sent as multipart/form-data with the signed copy."""

    mta = ScopedRelatedField(model=MtaTemplate, scope=lab_mtas)
    signer_name = serializers.CharField(max_length=200)
    signer_email = serializers.EmailField(
        max_length=254, required=False, allow_blank=True, default=""
    )
    signer_role = serializers.ChoiceField(choices=SignerRole.choices)
    authorised_signatory = serializers.BooleanField()
    accepted_on = serializers.DateField()
    file = serializers.FileField(allow_empty_file=False)

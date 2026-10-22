"""Distribution (#18, part A): who may receive material, the documents they show, the requests
with their lines, and the vials reserved at approval (ADR 0008, D18 and D19, amendment of
2026-10-20; ADR 0009, amendment of the same day).

A requester is an institution, never a private person: a legal person or a natural person
licensed to do business, with a microbiology laboratory the curator confirmed (DSMZ, CCM, CECT
all supply only such laboratories). Its responsible scientist is a deposits.Contact (D11), and
the contact's postal address is the delivery address, the laboratory's: personal data stays out
of every audited row and goes with an erasure.

A recipient permit is a document the requester holds (a SÚJB permit, a Letter of Authority, a
contained-use authorisation): never deleted, ended with a day and a reason. Its file is a
Document, frozen with its SHA-256 like an MTA version's text.

A request has a number per lab and year, a requester, the destination copied from it, the use
(D10) and the end use in words, and the containment level the requester declares. It is
submitted, then approved, rejected or cancelled. Its lines name a strain, a number of vials, and
the terms and MTA version the request was entered under (pinned). The policy (policy.py) decides
on them; approval writes the permits each line was approved against and reserves one vial per
row, only from lineage.selectors.distributable(). Stock stays a query: there is no counter.

Shipment, its two-person confirmation, the register entry, the handover protocol and the
delivery note are part B: approved > shipped, a reservation ended as shipped.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from cultures.core.models import PublicModel
from cultures.deposits.models import Contact, DepositTerms, MtaTemplate, Use
from cultures.labs.models import Lab
from cultures.labs.querysets import LabScopedQuerySet
from cultures.lineage.models import Vial
from cultures.strains.countries import COUNTRY_CODES
from cultures.strains.models import Strain

REQUEST_NUMBER_UNIQUE = "distribution_request_lab_year_number_uniq"
COUNTER_UNIQUE = "distribution_counter_lab_year_uniq"
LINE_STRAIN_UNIQUE = "distribution_line_request_strain_uniq"
ACCEPTANCE_UNIQUE = "distribution_acceptance_request_mta_uniq"
LINE_PERMIT_UNIQUE = "distribution_linepermit_line_permit_uniq"
ONE_OPEN_RESERVATION = "distribution_reservation_one_open_per_vial"

TRIMMED = r"^\S(.*\S)?$"
# A request asks for at most this many vials of one strain: more is a production order.
MAX_VIALS_PER_LINE = 50
# The largest file of a permit or a signed MTA. A scan of a few pages fits.
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
COUNTRIES = sorted(COUNTRY_CODES)


def trimmed_or_empty(field: str) -> Q:
    return Q(**{field: ""}) | Q(**{f"{field}__regex": TRIMMED})


class LegalForm(models.TextChoices):
    """Who may receive material: an institution, never a private person (act 78/2004 Sb.,
    § 16(1) for a GMO; every collection read supplies only institutions)."""

    LEGAL_PERSON = "legal_person", "Legal person (an institution or a company)"
    BUSINESS = "business", "Natural person licensed to do business"


class Requester(PublicModel):
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    # The responsible scientist, and in the contact's postal address the delivery address of
    # the laboratory. Personal data, so in deposits.Contact (ADR 0008, D11).
    contact = models.OneToOneField(Contact, on_delete=models.PROTECT, related_name="requester")
    institution = models.CharField(max_length=200)
    legal_form = models.CharField(max_length=20, choices=LegalForm.choices)
    # The company number (IČO in the Czech Republic), if it has one: the register asks for it.
    registration_number = models.CharField(max_length=40, blank=True)
    country = models.CharField(max_length=2)  # ISO 3166-1 alpha-2, where the laboratory is
    # How the curator confirmed that the institution has a microbiology laboratory: the page,
    # the document or the call, in a sentence that names no person.
    lab_evidence = models.TextField()
    lab_confirmed_on = models.DateField()

    objects = LabScopedQuerySet["Requester"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.CheckConstraint(
                condition=Q(institution__regex=TRIMMED),
                name="distribution_requester_institution_trimmed",
            ),
            models.CheckConstraint(
                condition=Q(legal_form__in=LegalForm.values),
                name="distribution_requester_legal_form_valid",
            ),
            models.CheckConstraint(
                condition=trimmed_or_empty("registration_number"),
                name="distribution_requester_registration_number_trimmed",
            ),
            models.CheckConstraint(
                condition=Q(country__in=COUNTRIES), name="distribution_requester_country_iso_3166"
            ),
            models.CheckConstraint(
                condition=Q(lab_evidence__regex=r"\S"),
                name="distribution_requester_lab_evidence_given",
            ),
        ]

    def __str__(self) -> str:
        return f"requester {self.public_id}"


class DocumentType(models.TextChoices):
    """The types a document may be, read from its first bytes, never from the name or header."""

    PDF = "application/pdf", "PDF"
    PNG = "image/png", "PNG image"
    JPEG = "image/jpeg", "JPEG image"


class Document(PublicModel):
    """A file a requester or a signer gave: a permit, a signed MTA. Frozen: a trigger refuses
    changes and deletes, and checks on insert that sha256 and size are those of the content.
    No file name is kept: a name often names a person, and the download names the document by
    its public id."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    content = models.BinaryField()
    content_type = models.CharField(max_length=40, choices=DocumentType.choices)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)

    objects = LabScopedQuerySet["Document"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.CheckConstraint(
                condition=Q(content_type__in=DocumentType.values),
                name="distribution_document_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(size_bytes__gte=1, size_bytes__lte=MAX_DOCUMENT_BYTES),
                name="distribution_document_size_range",
            ),
        ]

    def __str__(self) -> str:
        return f"document {self.public_id}"


class PermitKind(models.TextChoices):
    """The documents a recipient shows before material goes out (s10, section 8)."""

    SUJB_VRAT = "sujb_vrat", "SÚJB permit to handle highly risky agents (VRAT)"
    SUJB_RAT_NOTICE = "sujb_rat_notice", "Notice to SÚJB of handling risky agents (RAT)"
    SUJB_EXCEPTION = "sujb_exception", "SÚJB decision allowing a VRAT to a non-holder"
    PLANT_HEALTH_LOA = "plant_health_loa", "Letter of Authority for a quarantine pest"
    GMO_CONTAINED_USE = "gmo_contained_use", "Authorisation for contained use of GMOs"
    PATHOGEN_WORK_PERMIT = "pathogen_work_permit", "Permit to work with pathogens"


K = PermitKind
# These name the agents or pests they cover, as written on them: the policy reads the strain's
# taxon there (act 281/2002 Sb., § 11(3) fixes the kinds in a VRAT permit; 2019/829 Annex II
# Part A names the pest).
NAMES_AGENTS: frozenset[PermitKind] = frozenset({K.SUJB_VRAT, K.SUJB_EXCEPTION, K.PLANT_HEALTH_LOA})


class RecipientPermit(PublicModel):
    """A document a requester holds. Never deleted: ended with the first day it no longer
    holds and a reason, so "which permit did the recipient hold that day" stays a query. Days
    are Czech days (biosafety.policy.permit_today): `expires_on` is the last valid day."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    requester = models.ForeignKey(Requester, on_delete=models.PROTECT, related_name="permits")
    kind = models.CharField(max_length=30, choices=PermitKind.choices)
    issuer = models.CharField(max_length=200)  # the authority, as on the document: "SÚJB"
    issuer_country = models.CharField(max_length=2)  # ISO 3166-1 alpha-2
    reference = models.CharField(max_length=200)
    valid_from = models.DateField()
    expires_on = models.DateField(null=True, blank=True)  # the last valid day, if it states one
    # The agents or pests it names, as written on it. Required for the kinds in NAMES_AGENTS.
    covers = models.TextField(blank=True)
    # A Letter of Authority: the quantity and the number of sendings it allows (2019/829,
    # Annex I and Art. 6(4)), and the endorsement of the member state of origin (Art. 6(2)),
    # which part B requires before a shipment.
    quantity_allowed = models.PositiveIntegerField(null=True, blank=True)
    sendings_allowed = models.PositiveIntegerField(null=True, blank=True)
    endorsement_reference = models.CharField(max_length=200, blank=True)
    endorsed_on = models.DateField(null=True, blank=True)
    # A contained-use authorisation: its category, 1 to 4 (act 78/2004 Sb., § 15).
    gmo_category = models.PositiveSmallIntegerField(null=True, blank=True)
    # A permit to work with pathogens: the highest risk group it covers.
    risk_group = models.PositiveSmallIntegerField(null=True, blank=True)
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="+")
    ended_on = models.DateField(null=True, blank=True)
    end_reason = models.TextField(blank=True)

    objects = LabScopedQuerySet["RecipientPermit"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.CheckConstraint(
                condition=Q(kind__in=PermitKind.values), name="distribution_permit_kind_valid"
            ),
            models.CheckConstraint(
                condition=Q(issuer__regex=TRIMMED), name="distribution_permit_issuer_trimmed"
            ),
            models.CheckConstraint(
                condition=Q(issuer_country__in=COUNTRIES),
                name="distribution_permit_issuer_country_iso_3166",
            ),
            models.CheckConstraint(
                condition=Q(reference__regex=TRIMMED), name="distribution_permit_reference_trimmed"
            ),
            models.CheckConstraint(
                condition=Q(expires_on__isnull=True) | Q(expires_on__gte=F("valid_from")),
                name="distribution_permit_expires_after_start",
            ),
            models.CheckConstraint(
                condition=Q(ended_on__isnull=True) | Q(ended_on__gte=F("valid_from")),
                name="distribution_permit_ends_after_start",
            ),
            models.CheckConstraint(
                condition=Q(ended_on__isnull=True, end_reason="")
                | Q(ended_on__isnull=False, end_reason__regex=r"\S"),
                name="distribution_permit_end_has_reason",
            ),
            models.CheckConstraint(
                condition=~Q(kind__in=NAMES_AGENTS) | Q(covers__regex=r"\S"),
                name="distribution_permit_names_what_it_covers",
            ),
            # isnull=False spelled out: a CHECK passes when its condition is NULL.
            models.CheckConstraint(
                condition=Q(
                    kind=K.PLANT_HEALTH_LOA,
                    quantity_allowed__isnull=False,
                    quantity_allowed__gte=1,
                    sendings_allowed__isnull=False,
                    sendings_allowed__gte=1,
                )
                | (
                    ~Q(kind=K.PLANT_HEALTH_LOA)
                    & Q(quantity_allowed__isnull=True, sendings_allowed__isnull=True)
                ),
                name="distribution_permit_quantity_iff_loa",
            ),
            models.CheckConstraint(
                condition=Q(endorsement_reference="", endorsed_on__isnull=True)
                | Q(
                    kind=K.PLANT_HEALTH_LOA,
                    endorsement_reference__regex=TRIMMED,
                    endorsed_on__isnull=False,
                ),
                name="distribution_permit_endorsement_of_loa",
            ),
            models.CheckConstraint(
                condition=Q(
                    kind=K.GMO_CONTAINED_USE,
                    gmo_category__isnull=False,
                    gmo_category__gte=1,
                    gmo_category__lte=4,
                )
                | (~Q(kind=K.GMO_CONTAINED_USE) & Q(gmo_category__isnull=True)),
                name="distribution_permit_category_iff_gmo",
            ),
            models.CheckConstraint(
                condition=Q(
                    kind=K.PATHOGEN_WORK_PERMIT,
                    risk_group__isnull=False,
                    risk_group__gte=1,
                    risk_group__lte=4,
                )
                | (~Q(kind=K.PATHOGEN_WORK_PERMIT) & Q(risk_group__isnull=True)),
                name="distribution_permit_risk_group_iff_work_permit",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.reference}"


class RequestStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


R = RequestStatus
# Which status may follow which. The request trigger (migration 0003) refuses every other pair,
# and tests/test_request_states.py tries all 16 against both. Part B adds approved > shipped.
REQUEST_EDGES: dict[RequestStatus, frozenset[RequestStatus]] = {
    R.SUBMITTED: frozenset({R.APPROVED, R.REJECTED, R.CANCELLED}),
    R.APPROVED: frozenset({R.CANCELLED}),
    R.REJECTED: frozenset(),
    R.CANCELLED: frozenset(),
}


class DistributionRequest(PublicModel):
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+", db_index=False)
    # Numbered per lab and year from RequestCounter under the lab lock: "2026/7".
    year = models.PositiveSmallIntegerField()
    number = models.PositiveIntegerField()
    requester = models.ForeignKey(Requester, on_delete=models.PROTECT, related_name="requests")
    # Copied from the requester when the request is entered, never typed twice.
    destination_country = models.CharField(max_length=2)
    use = models.CharField(max_length=40, choices=Use.choices)  # D10
    # What the recipient will do with it, in words (2021/821 Art. 12(4), 281/2002 § 14(8)
    # ask for a concrete purpose). Names no person.
    end_use = models.TextField()
    # The containment level the requester declares for its laboratory (Directive 2000/54/EC).
    containment_level = models.PositiveSmallIntegerField()
    status = models.CharField(
        max_length=20, choices=RequestStatus.choices, default=RequestStatus.SUBMITTED
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    # Who approved or rejected it, and when. Part B refuses a shipment of a regulated line
    # confirmed by the person who approved it (ADR 0009, two-person rule).
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    # Required for a rejection, and for an approval a manager gives over findings. Names nobody.
    decision_reason = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True)

    objects = LabScopedQuerySet["DistributionRequest"].as_manager()

    @property
    def label(self) -> str:
        return f"{self.year}/{self.number}"

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(fields=["lab", "year", "number"], name=REQUEST_NUMBER_UNIQUE),
            models.CheckConstraint(
                condition=Q(number__gte=1), name="distribution_request_number_positive"
            ),
            models.CheckConstraint(
                condition=Q(destination_country__in=COUNTRIES),
                name="distribution_request_destination_iso_3166",
            ),
            models.CheckConstraint(
                condition=Q(use__in=Use.values), name="distribution_request_use_valid"
            ),
            models.CheckConstraint(
                condition=Q(end_use__regex=r"\S"), name="distribution_request_end_use_given"
            ),
            models.CheckConstraint(
                condition=Q(containment_level__gte=1, containment_level__lte=4),
                name="distribution_request_containment_1_to_4",
            ),
            # Each status with exactly its facts; no other status passes.
            models.CheckConstraint(
                condition=Q(
                    status=R.SUBMITTED,
                    decided_by__isnull=True,
                    decided_at__isnull=True,
                    decision_reason="",
                    cancelled_by__isnull=True,
                    cancelled_at__isnull=True,
                    cancel_reason="",
                )
                | Q(
                    status=R.APPROVED,
                    decided_by__isnull=False,
                    decided_at__isnull=False,
                    cancelled_by__isnull=True,
                    cancelled_at__isnull=True,
                    cancel_reason="",
                )
                | Q(
                    status=R.REJECTED,
                    decided_by__isnull=False,
                    decided_at__isnull=False,
                    decision_reason__regex=r"\S",
                    cancelled_by__isnull=True,
                    cancelled_at__isnull=True,
                    cancel_reason="",
                )
                | Q(
                    status=R.CANCELLED,
                    cancelled_by__isnull=False,
                    cancelled_at__isnull=False,
                    cancel_reason__regex=r"\S",
                ),
                name="distribution_request_facts_of_status",
            ),
        ]
        indexes = [
            models.Index(
                fields=["lab", "status", "-year", "-number"], name="distribution_request_list_idx"
            )
        ]

    def __str__(self) -> str:
        return f"request {self.label}"


class RequestCounter(models.Model):
    """The last request number of a lab in a year. Read and raised only under the lab lock."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+", db_index=False)
    year = models.PositiveSmallIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    objects = LabScopedQuerySet["RequestCounter"].as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lab", "year"], name=COUNTER_UNIQUE),
        ]

    def __str__(self) -> str:
        return f"{self.lab_id} {self.year}: {self.last_number}"


class RequestLine(PublicModel):
    """One strain of a request. Never changed: the terms and MTA version are those in force
    when the request was entered (BCCM MTA, clause 14), held by the line trigger."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    # No index of its own: the unique (request, strain) leads with it.
    request = models.ForeignKey(
        DistributionRequest, on_delete=models.PROTECT, related_name="lines", db_index=False
    )
    strain = models.ForeignKey(Strain, on_delete=models.PROTECT, related_name="request_lines")
    quantity = models.PositiveSmallIntegerField()
    terms = models.ForeignKey(DepositTerms, on_delete=models.PROTECT, related_name="+")
    # The terms' MTA version, or none when the terms name none (the policy then blocks).
    mta = models.ForeignKey(
        MtaTemplate, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )

    objects = LabScopedQuerySet["RequestLine"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(fields=["request", "strain"], name=LINE_STRAIN_UNIQUE),
            models.CheckConstraint(
                condition=Q(quantity__gte=1, quantity__lte=MAX_VIALS_PER_LINE),
                name="distribution_line_quantity_range",
            ),
        ]

    def __str__(self) -> str:
        return f"line {self.public_id}"


class LinePermit(models.Model):
    """A permit a line was approved against, written at approval, never changed: the decision
    can be replayed (s10, section 8)."""

    # No index of its own: the unique (line, permit) leads with it.
    line = models.ForeignKey(
        RequestLine, on_delete=models.PROTECT, related_name="permits", db_index=False
    )
    permit = models.ForeignKey(RecipientPermit, on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["line", "permit"], name=LINE_PERMIT_UNIQUE),
        ]

    def __str__(self) -> str:
        return f"{self.line_id}: {self.permit_id}"


class SignerRole(models.TextChoices):
    RESPONSIBLE_SCIENTIST = "responsible_scientist", "Responsible scientist"
    HEAD_OF_INSTITUTION = "head_of_institution", "Head of the institution or department"
    AUTHORISED_REPRESENTATIVE = "authorised_representative", "Authorised representative"


class MtaAcceptance(PublicModel):
    """The requester's acceptance of one MTA version for one request, recorded by a curator
    from the signed copy (its file is the evidence). Never changed. The MTA binds the
    institution, so only an acceptance signed by someone with authority to bind it counts
    (ATCC MTA: persons with full authority to bind)."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    # No index of its own: the unique (request, mta) leads with it.
    request = models.ForeignKey(
        DistributionRequest, on_delete=models.PROTECT, related_name="acceptances", db_index=False
    )
    mta = models.ForeignKey(MtaTemplate, on_delete=models.PROTECT, related_name="+")
    # Who signed: a person, so a contact (D11), erased with an erasure request.
    signer = models.OneToOneField(Contact, on_delete=models.PROTECT, related_name="+")
    signer_role = models.CharField(max_length=30, choices=SignerRole.choices)
    authorised_signatory = models.BooleanField()
    accepted_on = models.DateField()
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="+")

    objects = LabScopedQuerySet["MtaAcceptance"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(fields=["request", "mta"], name=ACCEPTANCE_UNIQUE),
            models.CheckConstraint(
                condition=Q(signer_role__in=SignerRole.values),
                name="distribution_acceptance_role_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"acceptance {self.public_id}"


class ReservationEnd(models.TextChoices):
    """Why a vial stopped being reserved. Part A ends reservations only on a cancellation;
    shipped comes with part B, deaccessioned with #20."""

    CANCELLED = "cancelled", "Request cancelled"
    SHIPPED = "shipped", "Shipped"
    DEACCESSIONED = "deaccessioned", "Strain deaccessioned"


class VialReservation(PublicModel):
    """One vial held for one line from its approval (D19, no expiry). Open while ended_at is
    null, at most one open per vial; an open reservation and the vial's status reserved go
    together (the deferred triggers of migration 0003)."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    line = models.ForeignKey(RequestLine, on_delete=models.PROTECT, related_name="reservations")
    vial = models.ForeignKey(Vial, on_delete=models.PROTECT, related_name="reservations")
    reserved_at = models.DateTimeField()
    reserved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    end_reason = models.CharField(max_length=20, choices=ReservationEnd.choices, blank=True)

    objects = LabScopedQuerySet["VialReservation"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["vial"], condition=Q(ended_at__isnull=True), name=ONE_OPEN_RESERVATION
            ),
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True, ended_by__isnull=True, end_reason="")
                | Q(
                    ended_at__isnull=False,
                    ended_by__isnull=False,
                    end_reason__in=ReservationEnd.values,
                ),
                name="distribution_reservation_end_complete",
            ),
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(ended_at__gte=F("reserved_at")),
                name="distribution_reservation_ended_after_reserved",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.vial_id} for {self.line_id}"

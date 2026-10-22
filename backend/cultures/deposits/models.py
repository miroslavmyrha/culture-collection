"""Depositors, deposits and the terms under which their material may be used (ADR 0008).

Contacts (D11): a person's name, e-mail, postal address and phone live in Contact,
which the row trigger does not watch (audit.registry.NOT_ROW_AUDITED). A
depositor points at one contact and holds the institution. Erasure empties the
contact in place; the depositor and its deposits stay.

Terms (D9, D10): a deposit's terms are versions. At most one is active, every
version lists a decision for every use, and its ABS facts follow Regulation
(EU) No 511/2014, Art. 4(3). A version may name one MTA template version,
whose text is frozen with its SHA-256.

Intake (D8): received > checking > accepted or rejected. Acceptance creates
the strain and its passage 0 (deposits.services). Receipt facts never change,
and neither does a decision: guard triggers hold both (migration 0003).
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from cultures.core.models import PublicModel
from cultures.labs.models import Lab
from cultures.labs.querysets import LabScopedQuerySet
from cultures.strains.countries import COUNTRY_CODES
from cultures.strains.models import PARTIAL_DATE, Strain

ONE_ACTIVE_TERMS = "deposits_depositterms_one_active"
TERMS_VERSION_UNIQUE = "deposits_depositterms_deposit_version_uniq"
MTA_VERSION_UNIQUE = "deposits_mtatemplate_lab_code_version_uniq"
TERMS_USE_UNIQUE = "deposits_termsuse_terms_use_uniq"

TRIMMED = r"^\S(.*\S)?$"
# An MTA template's code: upper-case letters, digits and hyphens, as printed on the agreement.
MTA_CODE = r"^[A-Z0-9][A-Z0-9-]{0,19}$"
# A telephone number as people write it: a digit or + first, then digits, spaces, ( ) and -.
PHONE = r"^[+0-9][0-9 ()-]{4,38}[0-9]$"


def trimmed_or_empty(field: str) -> Q:
    return Q(**{field: ""}) | Q(**{f"{field}__regex": TRIMMED})


class Contact(PublicModel):
    """A person a lab deals with: a depositor now, a requester later (#18). Personal data, so
    outside the row audit; events say only that a field changed."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=200)
    email = models.EmailField(max_length=254, blank=True)
    postal_address = models.TextField(blank=True)
    # A telephone number, as written: digits, spaces and + ( ) - only. The responsible person of
    # a shipment (#88) is reached by it at all times (WHO transport guidance, 8.1).
    phone = models.CharField(max_length=40, blank=True, default="", db_default="")
    # Set by contact_erase: the values above are gone, the row stays for the depositor.
    erased_at = models.DateTimeField(null=True, blank=True)

    objects = LabScopedQuerySet["Contact"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.CheckConstraint(
                condition=Q(erased_at__isnull=True, name__regex=TRIMMED)
                | Q(erased_at__isnull=False, name="", email="", postal_address="", phone=""),
                name="deposits_contact_named_unless_erased",
            ),
            models.CheckConstraint(
                condition=Q(email="") | Q(email__regex=r"^[^@\s]+@[^@\s]+$"),
                name="deposits_contact_email_shape",
            ),
            models.CheckConstraint(
                condition=Q(postal_address="") | Q(postal_address__regex=r"^\S(.*\S)?$"),
                name="deposits_contact_postal_address_trimmed",
            ),
            models.CheckConstraint(
                condition=Q(phone="") | Q(phone__regex=PHONE),
                name="deposits_contact_phone_shape",
            ),
        ]

    def __str__(self) -> str:
        return f"contact {self.public_id}"  # never the name: str() ends up in logs


class Depositor(PublicModel):
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    contact = models.OneToOneField(Contact, on_delete=models.PROTECT, related_name="depositor")
    # The organisation the depositor deposits for. Empty for a private person.
    institution = models.CharField(max_length=200, blank=True)

    objects = LabScopedQuerySet["Depositor"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.CheckConstraint(
                condition=trimmed_or_empty("institution"),
                name="deposits_depositor_institution_trimmed",
            ),
        ]

    def __str__(self) -> str:
        return f"depositor {self.public_id}"


class MtaTemplate(PublicModel):
    """One version of a lab's material transfer agreement. Frozen: a trigger refuses changes
    and deletes, and checks that text_sha256 is the SHA-256 of the text as stored."""

    # No index of its own: the unique (lab, code, version) leads with lab.
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+", db_index=False)
    code = models.CharField(max_length=20)
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    text = models.TextField()
    text_sha256 = models.CharField(max_length=64)

    objects = LabScopedQuerySet["MtaTemplate"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(fields=["lab", "code", "version"], name=MTA_VERSION_UNIQUE),
            models.CheckConstraint(
                condition=Q(code__regex=MTA_CODE), name="deposits_mtatemplate_code_format"
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="deposits_mtatemplate_version_positive"
            ),
            models.CheckConstraint(
                condition=Q(title__regex=TRIMMED), name="deposits_mtatemplate_title_trimmed"
            ),
            models.CheckConstraint(
                condition=Q(text__regex=r"\S"), name="deposits_mtatemplate_text_given"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} v{self.version}"


class DepositStatus(models.TextChoices):
    """ADR 0008, D8: received > checking > accepted or rejected."""

    RECEIVED = "received"
    CHECKING = "checking"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Condition(models.TextChoices):
    """How the material arrived. Anything but intact needs a note."""

    INTACT = "intact", "Intact"
    DAMAGED = "damaged", "Container or packaging damaged"
    OTHER = "other", "Other, see the note"


class Deposit(PublicModel):
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+", db_index=False)
    depositor = models.ForeignKey(Depositor, on_delete=models.PROTECT, related_name="deposits")
    status = models.CharField(max_length=20, choices=DepositStatus.choices)
    received_on = models.DateField()
    condition = models.CharField(max_length=20, choices=Condition.choices)
    # Free text about the material, naming no person.
    condition_note = models.TextField(blank=True)
    # As the depositor gave it; the strain takes it at acceptance and never changes it.
    name_as_received = models.CharField(max_length=200)
    # The passage count the depositor states, if any (ADR 0008, D3).
    depositor_passages = models.PositiveSmallIntegerField(null=True, blank=True)
    strain = models.OneToOneField(
        Strain, on_delete=models.PROTECT, related_name="deposit", null=True, blank=True
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    objects = LabScopedQuerySet["Deposit"].as_manager()

    class Meta(PublicModel.Meta):
        indexes = [
            models.Index(fields=["lab", "status", "-received_on"], name="deposits_lab_status_idx")
        ]
        constraints = [
            *PublicModel.Meta.constraints,
            models.CheckConstraint(
                condition=Q(name_as_received__regex=TRIMMED),
                name="deposits_deposit_name_as_received_trimmed",
            ),
            models.CheckConstraint(
                condition=Q(condition=Condition.INTACT)
                | (Q(condition__in=Condition.values) & Q(condition_note__regex=r"\S")),
                name="deposits_deposit_condition_noted",
            ),
            models.CheckConstraint(
                condition=Q(status=DepositStatus.ACCEPTED, strain__isnull=False)
                | (~Q(status=DepositStatus.ACCEPTED) & Q(strain__isnull=True)),
                name="deposits_deposit_strain_iff_accepted",
            ),
            models.CheckConstraint(
                condition=Q(status=DepositStatus.REJECTED, rejection_reason__regex=r"\S")
                | (~Q(status=DepositStatus.REJECTED) & Q(rejection_reason="")),
                name="deposits_deposit_reason_iff_rejected",
            ),
            # Also the one check on the status: no other value passes either branch.
            models.CheckConstraint(
                condition=Q(
                    status__in=[DepositStatus.ACCEPTED, DepositStatus.REJECTED],
                    decided_at__isnull=False,
                )
                | Q(
                    status__in=[DepositStatus.RECEIVED, DepositStatus.CHECKING],
                    decided_at__isnull=True,
                ),
                name="deposits_deposit_decided_iff_decision",
            ),
        ]

    def __str__(self) -> str:
        return f"deposit {self.public_id}"


class AbsScope(models.TextChoices):
    """Whether Regulation (EU) No 511/2014 applies to the material."""

    NOT_IN_SCOPE = "not_in_scope", "Not in scope"
    IN_SCOPE = "in_scope", "In scope"
    UNKNOWN = "unknown", "Unknown"


class Use(models.TextChoices):
    """ADR 0008, D10: what the material may be used for. To be confirmed with the curators.
    MTA permissions, not ABS utilisation."""

    RESEARCH_NONCOMMERCIAL = "research_noncommercial", "Non-commercial research"
    RESEARCH_COMMERCIAL = "research_commercial", "Commercial research"
    TEACHING = "teaching", "Teaching"
    DIAGNOSTICS = "diagnostics", "Diagnostics"
    PRODUCTION = "production", "Production"
    REFERENCE_QC = "reference_qc", "Reference material and quality control"
    PATENT_DEPOSIT_RELATED = "patent_deposit_related", "Related to a patent deposit"
    REDISTRIBUTION = "redistribution", "Redistribution to third parties"


class Decision(models.TextChoices):
    PERMIT = "permit", "Permitted"
    DENY = "deny", "Not permitted"
    ON_REQUEST = "on_request", "On request to the depositor"


class DepositTerms(PublicModel):
    """One version of a deposit's terms. Never changed: a new version replaces it, with a
    reason, and only `is_active` moves."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    # No index of its own: the unique (deposit, version) leads with deposit.
    deposit = models.ForeignKey(
        Deposit, on_delete=models.PROTECT, related_name="terms", db_index=False
    )
    version = models.PositiveIntegerField()
    is_active = models.BooleanField()
    mta = models.ForeignKey(
        MtaTemplate, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    # ABS facts (511/2014, Art. 4(3)).
    abs_scope = models.CharField(max_length=20, choices=AbsScope.choices)
    country_of_origin = models.CharField(max_length=2, blank=True)  # ISO 3166-1 alpha-2
    collection_date = models.CharField(max_length=10, blank=True)  # strains.models.PARTIAL_DATE
    pic_reference = models.CharField(max_length=200, blank=True)
    mat_reference = models.CharField(max_length=200, blank=True)
    ircc = models.CharField(max_length=100, blank=True)  # the IRCC's identifier in the ABSCH
    permit_reference = models.CharField(max_length=200, blank=True)
    # The uses by a subsequent user that the mutually agreed terms cover (in scope only, ADR 0008
    # amendment of 2026-10-20). Empty for material in scope: the MAT lets nothing go to a third
    # party, so distribution refuses every use (#18).
    mat_uses = ArrayField(
        models.CharField(max_length=40, choices=Use.choices), default=list, db_default=[]
    )
    # Why this version replaced the one before. Empty on version 1. Names no person.
    reason = models.TextField(blank=True)

    objects = LabScopedQuerySet["DepositTerms"].as_manager()

    class Meta(PublicModel.Meta):
        verbose_name_plural = "deposit terms"
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(fields=["deposit", "version"], name=TERMS_VERSION_UNIQUE),
            models.UniqueConstraint(
                fields=["deposit"], condition=Q(is_active=True), name=ONE_ACTIVE_TERMS
            ),
            models.CheckConstraint(
                condition=Q(version=1, reason="") | Q(version__gt=1, reason__regex=r"\S"),
                name="deposits_depositterms_reason_after_first",
            ),
            models.CheckConstraint(
                condition=Q(abs_scope__in=AbsScope.values), name="deposits_depositterms_scope_valid"
            ),
            # 511/2014, Art. 4(3)(a): material in scope comes with its internationally
            # recognised certificate of compliance, or else the permit of access.
            models.CheckConstraint(
                condition=~Q(abs_scope=AbsScope.IN_SCOPE) | ~Q(ircc="") | ~Q(permit_reference=""),
                name="deposits_depositterms_in_scope_has_ircc_or_permit",
            ),
            models.CheckConstraint(
                condition=Q(mat_uses__contained_by=Use.values),
                name="deposits_depositterms_mat_uses_valid",
            ),
            # The MAT is a fact of material in scope of 511/2014 only.
            models.CheckConstraint(
                condition=Q(abs_scope=AbsScope.IN_SCOPE) | Q(mat_uses=[]),
                name="deposits_depositterms_mat_uses_in_scope_only",
            ),
            models.CheckConstraint(
                condition=Q(country_of_origin="") | Q(country_of_origin__in=sorted(COUNTRY_CODES)),
                name="deposits_depositterms_country_iso_3166",
            ),
            models.CheckConstraint(
                condition=Q(collection_date="") | Q(collection_date__regex=PARTIAL_DATE),
                name="deposits_depositterms_collection_date_iso_8601",
            ),
            *(
                models.CheckConstraint(
                    condition=trimmed_or_empty(field), name=f"deposits_depositterms_{field}_trimmed"
                )
                for field in ("pic_reference", "mat_reference", "ircc", "permit_reference")
            ),
        ]

    def __str__(self) -> str:
        return f"terms v{self.version} of {self.deposit_id}"


class TermsUse(models.Model):
    """One use in one terms version, with its decision. Never changed."""

    # No index of its own: the unique (terms, use) leads with terms.
    terms = models.ForeignKey(
        DepositTerms, on_delete=models.PROTECT, related_name="uses", db_index=False
    )
    use = models.CharField(max_length=40, choices=Use.choices)
    decision = models.CharField(max_length=20, choices=Decision.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["terms", "use"], name=TERMS_USE_UNIQUE),
            models.CheckConstraint(
                condition=Q(use__in=Use.values) & Q(decision__in=Decision.values),
                name="deposits_termsuse_values_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.use}: {self.decision}"

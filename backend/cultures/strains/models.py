"""Strains of a lab: the registry entry, its identification history and its restrictions.

Identity (ADR 0008, D2): `accession_number` is the number as displayed,
unique per lab without regard to case; `accession_seq` is the number taken
from the lab's StrainCounter under the lab lock, unique per lab. Both are
written once and never change, and a number is never given to another strain:
strains are never deleted (a database trigger refuses both, migration 0003).
A strain waiting for acceptance (#12) is pending and has no number yet.

Taxonomy (D4): `name_as_received` is the depositor's name and never changes.
Every identification is a StrainIdentification row; exactly one is current,
and its taxon is cached on the strain for filters.

Biosafety (ADR 0009): a risk group 1 to 4, pathogenicity for animals and for
plants as separate fields, and any number of restrictions. A restriction ends only through a
proposal a second person confirms (#105): one person lifting it alone would take the strain out
of every rule that reads "regulated" from the active restrictions.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Upper

from cultures.biosafety.models import RestrictionKind
from cultures.core.models import PublicModel
from cultures.growth.models import GrowthConditions, growth_constraints, medium_index
from cultures.labs.models import Lab
from cultures.labs.querysets import LabScopedQuerySet
from cultures.taxonomy.models import Taxon

from .countries import COUNTRY_CODES

ACCESSION_NUMBER_UNIQUE = "strains_strain_accession_number_uniq"
ACCESSION_SEQ_UNIQUE = "strains_strain_lab_accession_seq_uniq"
ONE_CURRENT_IDENTIFICATION = "strains_identification_one_current"
ACTIVE_RESTRICTION_UNIQUE = "strains_restriction_active_uniq"
ONE_OPEN_END_PROPOSAL = "strains_endproposal_one_open"

# ISO 8601 calendar dates of reduced precision: a year, a year and a month, or a full date
# (the precision Darwin Core's eventDate allows). An isolation date is often known to the
# year only, and a full date would invent the rest.
PARTIAL_DATE = r"^[0-9]{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01]))?)?$"
# A dual-use item of the biological part of Annex I of Regulation (EU) 2021/821:
# 1C351 (pathogens and toxins), 1C353 (genetic elements, GMOs), 1C354 (plant pathogens),
# optionally down to a lettered and numbered sub-item (1C351.c, 1C351.a.1).
DUAL_USE_ENTRY = r"^1C35[134](\.[a-e](\.[0-9]{1,2})?)?$"
# The delegated act Annex I was read in, as the Official Journal cites it: (EU) 2025/2003.
EU_ACT = r"^\(EU\) [0-9]{4}/[0-9]{1,5}$"


class StrainStatus(models.TextChoices):
    """ADR 0008, D8: pending > active <> restricted > deaccessioned."""

    PENDING = "pending"
    ACTIVE = "active"
    RESTRICTED = "restricted"
    DEACCESSIONED = "deaccessioned"


class Pathogenicity(models.TextChoices):
    """For animals and for plants, which the human risk group does not rate (ADR 0009).

    Three values, as CCM's accession form asks it (IF-7805, item 6: man, animal, plant,
    unknown): unknown is what most deposits state, and "none known" is a statement about
    the literature, not a proof that the strain is harmless.
    """

    UNKNOWN = "unknown", "Unknown"
    NONE_KNOWN = "none_known", "No pathogenicity known"
    PATHOGENIC = "pathogenic", "Pathogenic"


class StrainCounter(models.Model):
    """The last sequence number given in a lab. Read and raised only under the lab lock."""

    lab = models.OneToOneField(Lab, on_delete=models.PROTECT, primary_key=True, related_name="+")
    last_seq = models.PositiveIntegerField(default=0)

    objects = LabScopedQuerySet["StrainCounter"].as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(last_seq__gte=0), name="strains_counter_seq_not_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.lab_id}: {self.last_seq}"


class Strain(PublicModel, GrowthConditions):
    # No index of its own: the unique (lab, accession_seq) below leads with lab.
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="strains", db_index=False)
    # "MYC 42". Null only while pending (#12). Unique per lab ignoring case (see Meta).
    accession_number = models.CharField(max_length=40, null=True, blank=True)  # noqa: DJ001 (null: no number yet)
    accession_seq = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=StrainStatus.choices)
    name_as_received = models.CharField(max_length=200)
    # The taxon of the current identification, cached for filters (strains.services keeps it).
    taxon = models.ForeignKey(Taxon, on_delete=models.PROTECT, related_name="+")
    risk_group = models.PositiveSmallIntegerField()
    animal_pathogenicity = models.CharField(max_length=20, choices=Pathogenicity.choices)
    plant_pathogenicity = models.CharField(max_length=20, choices=Pathogenicity.choices)
    # Origin (OECD BRC guidelines, General 10.2: source or host, date of isolation, at least
    # the country). Each may be unknown.
    isolation_source = models.CharField(max_length=200, blank=True)
    country_of_origin = models.CharField(max_length=2, blank=True)  # ISO 3166-1 alpha-2
    isolation_date = models.CharField(max_length=10, blank=True)  # PARTIAL_DATE

    objects = LabScopedQuerySet["Strain"].as_manager()

    class Meta(PublicModel.Meta):
        indexes = [medium_index("strains_growth_medium_idx")]
        constraints = [
            *PublicModel.Meta.constraints,
            # One expression first and lab second: django-migration-linter 6.0.0 misreads
            # the table of an index whose definition has a second "(".
            *growth_constraints("strains_strain"),
            models.UniqueConstraint(Upper("accession_number"), "lab", name=ACCESSION_NUMBER_UNIQUE),
            models.UniqueConstraint(fields=["lab", "accession_seq"], name=ACCESSION_SEQ_UNIQUE),
            models.CheckConstraint(
                condition=Q(accession_seq__isnull=True) | Q(accession_seq__gte=1),
                name="strains_strain_accession_seq_positive",
            ),
            models.CheckConstraint(
                condition=Q(accession_number__isnull=True)
                | Q(accession_number__regex=r"^\S(.*\S)?$"),
                name="strains_strain_accession_number_trimmed",
            ),
            # A number from the counter comes with its text; a pending strain has neither.
            models.CheckConstraint(
                condition=Q(accession_seq__isnull=True) | Q(accession_number__isnull=False),
                name="strains_strain_seq_has_number",
            ),
            models.CheckConstraint(
                condition=Q(status=StrainStatus.PENDING, accession_number__isnull=True)
                | (
                    ~Q(status=StrainStatus.PENDING)
                    & Q(status__in=StrainStatus.values)
                    & Q(accession_number__isnull=False)
                ),
                name="strains_strain_numbered_unless_pending",
            ),
            models.CheckConstraint(
                condition=Q(name_as_received__regex=r"^\S(.*\S)?$"),
                name="strains_strain_name_as_received_trimmed",
            ),
            models.CheckConstraint(
                condition=Q(risk_group__gte=1, risk_group__lte=4),
                name="strains_strain_risk_group_1_to_4",
            ),
            models.CheckConstraint(
                condition=Q(animal_pathogenicity__in=Pathogenicity.values)
                & Q(plant_pathogenicity__in=Pathogenicity.values),
                name="strains_strain_pathogenicity_valid",
            ),
            models.CheckConstraint(
                condition=Q(country_of_origin="") | Q(country_of_origin__in=sorted(COUNTRY_CODES)),
                name="strains_strain_country_iso_3166",
            ),
            models.CheckConstraint(
                condition=Q(isolation_date="") | Q(isolation_date__regex=PARTIAL_DATE),
                name="strains_strain_isolation_date_iso_8601",
            ),
            models.CheckConstraint(
                condition=Q(isolation_source="") | Q(isolation_source__regex=r"^\S(.*\S)?$"),
                name="strains_strain_isolation_source_trimmed",
            ),
        ]

    def __str__(self) -> str:
        return self.accession_number or f"pending {self.public_id}"


class StrainIdentification(PublicModel):
    """One identification of a strain: which taxon, when, how and why. Never changed but for
    `is_current`, which moves to the newer row on a reclassification."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    strain = models.ForeignKey(Strain, on_delete=models.PROTECT, related_name="identifications")
    taxon = models.ForeignKey(Taxon, on_delete=models.PROTECT, related_name="+")
    identified_on = models.DateField()
    # How it was identified, as the lab names it ("16S rRNA gene sequence"). Free text that
    # names no person.
    method = models.CharField(max_length=200)
    reason = models.TextField()
    is_current = models.BooleanField()

    objects = LabScopedQuerySet["StrainIdentification"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["strain"], condition=Q(is_current=True), name=ONE_CURRENT_IDENTIFICATION
            ),
            models.CheckConstraint(
                condition=Q(method__regex=r"^\S(.*\S)?$"),
                name="strains_identification_method_trimmed",
            ),
            models.CheckConstraint(
                condition=Q(reason__regex=r"\S"), name="strains_identification_reason_given"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.strain_id}: {self.taxon_id} on {self.identified_on}"


class StrainRestriction(PublicModel):
    """A strain on a regulatory list (ADR 0009, Restriction kinds). Ended, never deleted."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    strain = models.ForeignKey(Strain, on_delete=models.PROTECT, related_name="restrictions")
    kind = models.CharField(max_length=20, choices=RestrictionKind.choices)
    # The list entry it was read in: the annex item of decree 474/2002 Sb., the Annex I entry
    # of 2021/821 (DUAL_USE_ENTRY), the Annex II entry of 2019/2072, or for a GMO the
    # notification or permit reference under act 78/2004 Sb.
    reference = models.CharField(max_length=100)
    # dual_use only: the delegated act whose Annex I was read, because the annex is replaced
    # every year.
    act = models.CharField(max_length=30, blank=True)
    # gmo only: the risk category of contained use, I to IV (act 78/2004 Sb., § 15).
    gmo_category = models.PositiveSmallIntegerField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.TextField(blank=True)

    objects = LabScopedQuerySet["StrainRestriction"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(
                F("strain"),
                F("kind"),
                F("reference"),
                condition=Q(ended_at__isnull=True),
                name=ACTIVE_RESTRICTION_UNIQUE,
            ),
            models.CheckConstraint(
                condition=Q(kind__in=RestrictionKind.values), name="strains_restriction_kind_valid"
            ),
            models.CheckConstraint(
                condition=Q(reference__regex=r"^\S(.*\S)?$"),
                name="strains_restriction_reference_trimmed",
            ),
            models.CheckConstraint(
                condition=~Q(kind=RestrictionKind.DUAL_USE) | Q(reference__regex=DUAL_USE_ENTRY),
                name="strains_restriction_dual_use_entry",
            ),
            models.CheckConstraint(
                condition=Q(kind=RestrictionKind.DUAL_USE, act__regex=EU_ACT)
                | (~Q(kind=RestrictionKind.DUAL_USE) & Q(act="")),
                name="strains_restriction_act_iff_dual_use",
            ),
            models.CheckConstraint(
                # isnull=False spelled out: a CHECK passes when its condition is NULL.
                condition=Q(
                    kind=RestrictionKind.GMO,
                    gmo_category__isnull=False,
                    gmo_category__gte=1,
                    gmo_category__lte=4,
                )
                | (~Q(kind=RestrictionKind.GMO) & Q(gmo_category__isnull=True)),
                name="strains_restriction_category_iff_gmo",
            ),
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True, end_reason="")
                | Q(ended_at__isnull=False, end_reason__regex=r"\S"),
                name="strains_restriction_end_has_reason",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.reference}"


class RestrictionEndProposal(PublicModel):
    """A proposal to end a restriction, with the reason (#105, ADR 0009). A manager other than
    the proposer confirms it, which ends the restriction with this reason at the confirmation's
    time; or someone withdraws it with a reason of their own. Inserted open; the one later
    change is the confirmation or the withdrawal, written once (the trigger). Never deleted. At
    most one per restriction is not withdrawn (a partial unique index)."""

    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    restriction = models.ForeignKey(
        StrainRestriction, on_delete=models.PROTECT, related_name="end_proposals"
    )
    # Why the restriction should end (an annex no longer lists the agent). It becomes the
    # restriction's end_reason. Names nobody.
    reason = models.TextField()
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    proposed_at = models.DateTimeField()
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    # Why it was withdrawn. Names nobody.
    withdraw_reason = models.TextField(blank=True)

    objects = LabScopedQuerySet["RestrictionEndProposal"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            # One not withdrawn: the open one, or the one confirmed (an ended restriction takes
            # no proposal, the trigger). So at most one is open, and one ended the restriction.
            models.UniqueConstraint(
                fields=["restriction"],
                condition=Q(withdrawn_at__isnull=True),
                name=ONE_OPEN_END_PROPOSAL,
            ),
            models.CheckConstraint(
                condition=Q(reason__regex=r"\S"), name="strains_endproposal_reason_given"
            ),
            models.CheckConstraint(
                condition=Q(confirmed_at__isnull=True, confirmed_by__isnull=True)
                | Q(confirmed_at__isnull=False, confirmed_by__isnull=False),
                name="strains_endproposal_confirmation_complete",
            ),
            models.CheckConstraint(
                condition=Q(
                    withdrawn_at__isnull=True, withdrawn_by__isnull=True, withdraw_reason=""
                )
                | Q(
                    withdrawn_at__isnull=False,
                    withdrawn_by__isnull=False,
                    withdraw_reason__regex=r"\S",
                ),
                name="strains_endproposal_withdrawal_complete",
            ),
            models.CheckConstraint(
                condition=Q(confirmed_at__isnull=True) | Q(withdrawn_at__isnull=True),
                name="strains_endproposal_confirmed_or_withdrawn",
            ),
            models.CheckConstraint(
                # Spelled with isnull: a CHECK passes when its condition is NULL.
                condition=Q(confirmed_by__isnull=True) | ~Q(confirmed_by=F("proposed_by")),
                name="strains_endproposal_second_person",
            ),
            models.CheckConstraint(
                condition=(Q(confirmed_at__isnull=True) | Q(confirmed_at__gte=F("proposed_at")))
                & (Q(withdrawn_at__isnull=True) | Q(withdrawn_at__gte=F("proposed_at"))),
                name="strains_endproposal_outcome_after_proposal",
            ),
        ]

    def __str__(self) -> str:
        return f"end proposal {self.public_id}"

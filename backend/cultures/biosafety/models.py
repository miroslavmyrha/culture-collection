"""Regulatory facts about agents and labs (ADR 0009). The app stores facts, nothing else.

The official lists themselves are RegulatoryList and RegulatoryListEntry (#169): decree
474/2002 Sb. annexes 1 and 2, the risk group tables of government order 361/2007 Sb. annex 7,
the biological entries of Regulation (EU) 2021/821 annex I and annex II of Implementing
Regulation (EU) 2019/2072. They are loaded from the data files of ``data/`` and changed by
nothing (``lists.py``, the guards of migration 0005).

RestrictionKind names the lists a strain can be on. A strain carries any
number of restrictions (strains.StrainRestriction). Two kinds may only be
held with a permit, recorded here as a LabAuthorisation of the lab:
- cz_vrat, a highly risky agent of decree 474/2002 Sb., Annex 1: a permit of
  SÚJB (act 281/2002 Sb., § 6);
- quarantine_pest, a Union quarantine pest of Implementing Regulation (EU)
  2019/2072, Annex II: a permit of ÚKZÚZ (act 326/2004 Sb., § 8).
Authorisations are never deleted. A permit that ends gets an end date and a
reason, so "which permit did the lab hold on that day" stays a query.
"""

from django.db import models
from django.db.models import F, Q

from cultures.core.models import PublicModel
from cultures.labs.models import Lab
from cultures.labs.querysets import LabScopedQuerySet

AUTHORISATION_UNIQUE = "biosafety_labauthorisation_lab_kind_reference_uniq"
LIST_VERSION_UNIQUE = "biosafety_regulatorylist_code_file_sha256_uniq"
LIST_ONE_CURRENT = "biosafety_regulatorylist_one_current"
LIST_ENTRY_UNIQUE = "biosafety_regulatorylistentry_list_code_uniq"
SHA256 = r"^[0-9a-f]{64}$"


class RestrictionKind(models.TextChoices):
    CZ_VRAT = "cz_vrat", "Highly risky agent (VRAT), decree 474/2002 Sb., Annex 1"
    CZ_RAT = "cz_rat", "Risky agent (RAT), decree 474/2002 Sb., Annex 2"
    DUAL_USE = "dual_use", "Dual-use item, Regulation (EU) 2021/821, Annex I"
    QUARANTINE_PEST = (
        "quarantine_pest",
        "Union quarantine pest, Regulation (EU) 2019/2072, Annex II",
    )
    GMO = "gmo", "Genetically modified organism in contained use, act 78/2004 Sb."


class AuthorisationKind(models.TextChoices):
    """The restriction kinds a lab may hold only with a permit (ADR 0009, Lab authorisation)."""

    CZ_VRAT = RestrictionKind.CZ_VRAT.value, "Permit to handle highly risky agents (VRAT)"
    QUARANTINE_PEST = RestrictionKind.QUARANTINE_PEST.value, "Permit to hold quarantine pests"


class DestructionMethod(models.TextChoices):
    """How material is destroyed (#160): one code on every destruction record, and the method a
    quarantine pest's permit declares (Regulation (EU) 2019/829, Annex I (i): "the method of
    destruction or treatment of the specified material on completion of the specified
    activity"). A short list and `other` described in words; how to inactivate a given agent is
    the lab's validated procedure, not the collection's."""

    AUTOCLAVE = "autoclave", "Autoclaving"
    CHEMICAL = "chemical", "Chemical inactivation"
    INCINERATION = "incineration", "Incineration"
    OTHER = "other", "Other"


class Issuer(models.TextChoices):
    SUJB = "sujb", "SÚJB"
    UKZUZ = "ukzuz", "ÚKZÚZ"


# Who issues the permit for each kind: act 281/2002 Sb. § 6 (SÚJB), act 326/2004 Sb. § 8 (ÚKZÚZ).
ISSUER_OF: dict[AuthorisationKind, Issuer] = {
    AuthorisationKind.CZ_VRAT: Issuer.SUJB,
    AuthorisationKind.QUARANTINE_PEST: Issuer.UKZUZ,
}


class LabAuthorisation(PublicModel):
    # No index of its own: the unique constraint below leads with lab.
    lab = models.ForeignKey(
        Lab, on_delete=models.PROTECT, related_name="authorisations", db_index=False
    )
    kind = models.CharField(max_length=20, choices=AuthorisationKind.choices)
    issuer = models.CharField(max_length=10, choices=Issuer.choices)
    permit_reference = models.CharField(max_length=100)
    valid_from = models.DateField()
    # The last day of validity as the permit states it. Empty: the permit states none.
    expires_on = models.DateField(null=True, blank=True)
    # The day the permit stopped being valid before its expiry (revoked, surrendered, entered
    # in error), with the reason. The row stays.
    ended_on = models.DateField(null=True, blank=True)
    end_reason = models.TextField(blank=True)
    # A quarantine pest's permit: the destruction method its application declared (Regulation
    # (EU) 2019/829, Annex I (i); ÚKZÚZ's form asks "Navrhovaná metoda případné likvidace").
    # A destruction record of a quarantine pest must use it (#160, decision Q6). Empty for a
    # VRAT permit, and for a quarantine permit recorded before #160: such a permit refuses every
    # destruction until staff record it again with its method.
    destruction_method = models.CharField(
        max_length=20, choices=DestructionMethod.choices, blank=True, db_default=""
    )

    objects = LabScopedQuerySet["LabAuthorisation"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["lab", "kind", "permit_reference"], name=AUTHORISATION_UNIQUE
            ),
            # The kind and its issuer go together; no other kind passes.
            models.CheckConstraint(
                condition=Q(kind=AuthorisationKind.CZ_VRAT, issuer=Issuer.SUJB)
                | Q(kind=AuthorisationKind.QUARANTINE_PEST, issuer=Issuer.UKZUZ),
                name="biosafety_labauthorisation_kind_issuer",
            ),
            models.CheckConstraint(
                condition=Q(permit_reference__regex=r"^\S(.*\S)?$"),
                name="biosafety_labauthorisation_reference_trimmed",
            ),
            models.CheckConstraint(
                condition=Q(expires_on__isnull=True) | Q(expires_on__gte=F("valid_from")),
                name="biosafety_labauthorisation_expires_after_start",
            ),
            models.CheckConstraint(
                condition=Q(ended_on__isnull=True) | Q(ended_on__gte=F("valid_from")),
                name="biosafety_labauthorisation_ends_after_start",
            ),
            models.CheckConstraint(
                condition=Q(destruction_method="")
                | Q(
                    kind=AuthorisationKind.QUARANTINE_PEST,
                    destruction_method__in=DestructionMethod.values,
                ),
                name="biosafety_labauthorisation_destruction_method_of_kind",
            ),
            # An end date if and only if a reason.
            models.CheckConstraint(
                condition=Q(ended_on__isnull=True, end_reason="")
                | Q(ended_on__isnull=False, end_reason__regex=r"\S"),
                name="biosafety_labauthorisation_end_has_reason",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_issuer_display()} {self.permit_reference}"


class ListCode(models.TextChoices):
    """The official lists the app holds (#169), one data file each under ``data/``."""

    CZ_474_2002 = "cz-474-2002", "Decree 474/2002 Sb., Annexes 1 and 2 (VRAT, RAT)"
    CZ_361_2007_ANNEX_7 = (
        "cz-361-2007-annex-7",
        "Government order 361/2007 Sb., Annex 7 (risk groups)",
    )
    EU_2021_821_ANNEX_I = (
        "eu-2021-821-annex-i",
        "Regulation (EU) 2021/821, Annex I, entries 1C351, 1C353 and 1C354 (dual-use)",
    )
    EU_2019_2072_ANNEX_II = (
        "eu-2019-2072-annex-ii",
        "Implementing Regulation (EU) 2019/2072, Annex II (Union quarantine pests)",
    )


# Which restriction a list's entry gives a strain, where the list is about one restriction.
# Annex 7 of 361/2007 is about risk groups, so its entries give no restriction, and the two
# annexes of 474/2002 give different ones (the entry's own `restriction_kind` says which).
LIST_RESTRICTIONS: dict[str, frozenset[str]] = {
    ListCode.CZ_474_2002: frozenset({RestrictionKind.CZ_VRAT, RestrictionKind.CZ_RAT}),
    ListCode.CZ_361_2007_ANNEX_7: frozenset(),
    ListCode.EU_2021_821_ANNEX_I: frozenset({RestrictionKind.DUAL_USE}),
    ListCode.EU_2019_2072_ANNEX_II: frozenset({RestrictionKind.QUARANTINE_PEST}),
}
# The one list that states a risk group.
RISK_GROUP_LIST = ListCode.CZ_361_2007_ANNEX_7


class EntryKind(models.TextChoices):
    """What an entry names, as its own list classes it (the data files' `kind`)."""

    ORGANISM = "organism", "An organism"
    TOXIN = "toxin", "A toxin or a subunit of one"
    GENETIC_ELEMENT = "genetic_element", "A genetic element or a modified organism"


class MatchScope(models.TextChoices):
    """How far an entry's `match_name` reaches (biosafety.lists): one taxon, or a whole genus."""

    EXACT = "exact", "That name, and a synonym of it"
    GENUS = "genus", "Every taxon of that genus"


class RegulatoryList(PublicModel):
    """One reading of one official list, with where it came from and what it was (#169).

    A data file whose SHA-256 the database already holds is loaded no second time, and a
    changed file becomes a new version: the new row is current and the one before it is not.
    The row and its entries are never edited and never deleted (migration 0005); the one
    change a list row takes is losing `is_current` to its successor.
    """

    code = models.CharField(max_length=30, choices=ListCode.choices)
    # The list's own title, act and source URL, as the data file records them.
    title = models.CharField(max_length=300)
    act = models.CharField(max_length=30)
    source_url = models.URLField(max_length=500)
    # The version the source names: the e-Sbirka version path, or the CELEX number.
    version = models.CharField(max_length=60)
    # The day that version applies from, and the day the text was fetched.
    version_date = models.DateField()
    fetched_on = models.DateField()
    # The SHA-256 of the fetched text, and of the data file in the repository.
    source_sha256 = models.CharField(max_length=64)
    file_sha256 = models.CharField(max_length=64)
    entry_count = models.PositiveIntegerField()
    loaded_at = models.DateTimeField()
    is_current = models.BooleanField()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            # One row per reading of a list: the same file loaded again is the same version.
            models.UniqueConstraint(fields=["code", "file_sha256"], name=LIST_VERSION_UNIQUE),
            models.UniqueConstraint(
                fields=["code"], condition=Q(is_current=True), name=LIST_ONE_CURRENT
            ),
            models.CheckConstraint(
                condition=Q(code__in=ListCode.values), name="biosafety_regulatorylist_code_valid"
            ),
            models.CheckConstraint(
                condition=Q(source_sha256__regex=SHA256) & Q(file_sha256__regex=SHA256),
                name="biosafety_regulatorylist_sha256_hex",
            ),
            models.CheckConstraint(
                condition=Q(entry_count__gte=1), name="biosafety_regulatorylist_has_entries"
            ),
            models.CheckConstraint(
                condition=Q(fetched_on__gte=F("version_date")),
                name="biosafety_regulatorylist_fetched_after_version",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.version}"


class RegulatoryListEntry(PublicModel):
    """One entry of one reading of a list: its code in the list, its name as the list writes it,
    and what the list says about it.

    `match_name` and `match_scope` are the scientific name derived from the name for the
    suggestions of #169 (biosafety.lists.match_of). An entry whose name yields none has
    neither and suggests nothing. Nothing matches by substring.
    """

    # No index of its own: the unique (list, code) below leads with list.
    list = models.ForeignKey(
        RegulatoryList, on_delete=models.PROTECT, related_name="entries", db_index=False
    )
    # The entry's identity inside its list: "I.I 1", "2.37", "1C351.a.4", "A.1".
    code = models.CharField(max_length=40)
    # The name the list itself prints, which is Czech prose in 474/2002 and a scientific name
    # with its authority in the EU annexes. Never edited, and never cut: one entry of annex II
    # of 2019/2072 runs to some three thousand characters (the vectors of one pest).
    name = models.TextField()
    kind = models.CharField(max_length=20, choices=EntryKind.choices)
    # The restriction this entry gives a strain, empty for an entry of the risk group tables.
    restriction_kind = models.CharField(
        max_length=20, choices=RestrictionKind.choices, blank=True, db_default=""
    )
    # The risk group the entry states, for an entry of annex 7 of 361/2007 that states one.
    risk_group = models.PositiveSmallIntegerField(null=True, blank=True)
    match_name = models.CharField(max_length=200, blank=True, db_default="")
    match_scope = models.CharField(
        max_length=10, choices=MatchScope.choices, blank=True, db_default=""
    )

    class Meta(PublicModel.Meta):
        indexes = [
            # Partial, and spelled without a negation: the linter reads a condition's
            # parentheses as a table name.
            models.Index(
                fields=["match_name"],
                condition=Q(match_name__gt=""),
                name="biosafety_entry_match_idx",
            ),
        ]
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(fields=["list", "code"], name=LIST_ENTRY_UNIQUE),
            models.CheckConstraint(
                condition=Q(code__regex=r"^\S(.*\S)?$"),
                name="biosafety_regulatorylistentry_code_trimmed",
            ),
            models.CheckConstraint(
                condition=Q(name__regex=r"^\S(.*\S)?$"),
                name="biosafety_regulatorylistentry_name_trimmed",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=EntryKind.values),
                name="biosafety_regulatorylistentry_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(restriction_kind="") | Q(restriction_kind__in=RestrictionKind.values),
                name="biosafety_regulatorylistentry_restriction_valid",
            ),
            # isnull=False spelled out: a CHECK passes when its condition is NULL.
            models.CheckConstraint(
                condition=Q(risk_group__isnull=True)
                | Q(risk_group__gte=1, risk_group__lte=4, risk_group__isnull=False),
                name="biosafety_regulatorylistentry_risk_group_1_to_4",
            ),
            # A match name and its scope go together, and the name is lower case, one space
            # between words: biosafety.lists compares it with a taxon's name the same way.
            models.CheckConstraint(
                condition=Q(match_name="", match_scope="")
                | Q(
                    match_name__regex=r"^[a-z][a-z-]+( [a-z.-]+)*$",
                    match_scope__in=MatchScope.values,
                ),
                name="biosafety_regulatorylistentry_match_name_with_scope",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"

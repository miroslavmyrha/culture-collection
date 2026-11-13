"""Reads of strains. Every one takes the access object, so the lab scope is in the signature."""

from dataclasses import dataclass
from enum import StrEnum

from django.db.models import (
    Count,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
)
from django.db.models.functions import Coalesce

from cultures.biosafety import selectors as biosafety_lists
from cultures.biosafety.models import RegulatoryListEntry, RestrictionKind
from cultures.deposits.models import Depositor
from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.lineage.models import Vial, VialStatus
from cultures.taxonomy.models import Taxon
from cultures.taxonomy.selectors import taxon_and_below

from .models import (
    RestrictionEndProposal,
    RiskGroupProposal,
    Strain,
    StrainDeaccessionProposal,
    StrainIdentification,
    StrainRestriction,
    StrainStatus,
)


def regulating_restrictions() -> QuerySet[StrainRestriction]:
    """The restrictions that make a strain regulated (ADR 0009): every active one, of any kind.
    An ended restriction regulates nothing. The one definition: the vial lists mask by it and
    the reveal decides by it (lineage), so the two cannot drift apart."""
    return StrainRestriction.objects.filter(ended_at__isnull=True)


def strain_rows(*, access: Access, lab: Lab) -> QuerySet[Strain]:
    """The strains of one lab the user may view, as bare rows: for a read about one of them
    (its history, its terms) that needs the strain only to scope the rest."""
    return Strain.objects.for_access(access, Perm.VIEW_STRAINS).filter(lab=lab).order_by("pk")


def in_collection(strains: QuerySet[Strain]) -> QuerySet[Strain]:
    """Without the deaccessioned ones (#20): what a list shows unless asked for them."""
    return strains.exclude(status=StrainStatus.DEACCESSIONED)


def distributable_vials() -> QuerySet[Vial]:
    """The vials that may go out: in the status available, of a released batch of distribution
    stock of a strain that still supplies (lineage.selectors.distributable, the one definition the
    batch figure and the distribution of vials read). What the list counts per strain and its
    filter asks for. A count says nothing of where a vial is, so it is not a location and the
    masking of regulated strains (ADR 0009) does not apply to it."""
    # lineage.selectors imports this module, so it is imported here, when called.
    from cultures.lineage.selectors import distributable  # noqa: PLC0415

    return Vial.objects.filter(distributable("batch__"), status=VialStatus.AVAILABLE)


def strain_list(*, access: Access, lab: Lab) -> QuerySet[Strain]:
    """The strains of one lab the user may view, by accession number (numbered first), each with
    `vials_distributable`, the number of its vials that may go out, from a subquery in the same
    query. Every status: the list's filter leaves out the deaccessioned ones unless asked
    (filters)."""
    vials = (
        distributable_vials()
        .filter(batch__strain=OuterRef("pk"))
        .order_by()
        .values("batch__strain")
        .annotate(n=Count("pk"))
        .values("n")
    )
    return (
        Strain.objects.for_access(access, Perm.VIEW_STRAINS)
        .filter(lab=lab)
        .select_related("taxon")
        .annotate(vials_distributable=Coalesce(Subquery(vials, output_field=IntegerField()), 0))
        .prefetch_related(
            Prefetch(
                "restrictions",
                queryset=StrainRestriction.objects.filter(ended_at__isnull=True).order_by(
                    "kind", "reference", "pk"
                ),
                to_attr="active_restrictions",
            )
        )
        .order_by(F("accession_seq").asc(nulls_last=True), "accession_number", "pk")
    )


def strain_detail(*, access: Access, lab: Lab) -> QuerySet[Strain]:
    """The same rows with their whole history: every identification and every restriction,
    whether the strain is regulated, the open proposals to deaccession it (#20) and to lower its
    risk group (#174), and the deposit it came from (#154), in the same query as the strain: the
    serializer shows that one only to a reader who may open deposits."""
    history = (
        strain_list(access=access, lab=lab)
        # risk_group_entry: the entry of annex 7 the group rests on (#169), joined so the
        # detail stays one query and the exact count holds.
        .select_related("growth_medium", "deposit", "risk_group_entry")
        .annotate(regulated=Exists(regulating_restrictions().filter(strain=OuterRef("pk"))))
        .prefetch_related(
            Prefetch(
                "identifications",
                queryset=StrainIdentification.objects.select_related("taxon").order_by(
                    "-is_current", "-identified_on", "-created_at", "-pk"
                ),
            )
        )
    )
    return (
        history.prefetch_related(
            # At most one is open (a unique index).
            Prefetch(
                "deaccession_proposals",
                queryset=StrainDeaccessionProposal.objects.filter(
                    confirmed_at__isnull=True, withdrawn_at__isnull=True
                ),
                to_attr="open_deaccession_proposals",
            )
        )
        .prefetch_related(
            # The open proposal to lower the risk group (#174): at most one (a unique index).
            Prefetch(
                "risk_group_proposals",
                queryset=RiskGroupProposal.objects.filter(
                    confirmed_at__isnull=True, withdrawn_at__isnull=True
                ).select_related("basis_entry"),
                to_attr="open_risk_group_proposals",
            )
        )
        .prefetch_related(
            Prefetch(
                "restrictions",
                # Active first, then the ended ones in the order they ended.
                queryset=StrainRestriction.objects.order_by(
                    F("ended_at").asc(nulls_first=True), "kind", "reference", "pk"
                ).prefetch_related(
                    # The open proposal to end it, if any (#105): at most one (a unique index).
                    Prefetch(
                        "end_proposals",
                        queryset=RestrictionEndProposal.objects.filter(
                            confirmed_at__isnull=True, withdrawn_at__isnull=True
                        ),
                        to_attr="open_end_proposals",
                    )
                ),
                to_attr="all_restrictions",
            ),
        )
    )


# Filters, applied to a scoped queryset only (filters.StrainFilter).


def under_taxon(strains: QuerySet[Strain], taxon: Taxon) -> QuerySet[Strain]:
    """Strains whose current taxon is the taxon (or its accepted name), below it, or a synonym
    of either: "genus Bacillus" finds B. subtilis, its subspecies and old names of both."""
    return strains.filter(taxon_id__in=taxon_and_below(taxon))


def with_restriction(strains: QuerySet[Strain], kind: RestrictionKind) -> QuerySet[Strain]:
    restricted = StrainRestriction.objects.filter(kind=kind, ended_at__isnull=True).values(
        "strain_id"
    )
    return strains.filter(pk__in=restricted)


def matching(strains: QuerySet[Strain], text: str) -> QuerySet[Strain]:
    """The accession number, the name as received or the current taxon's name contains the text."""
    text = " ".join(text.split())
    if not text:
        return strains
    return strains.filter(
        Q(accession_number__icontains=text)
        | Q(name_as_received__icontains=text)
        | Q(taxon__name__icontains=text)
    )


def with_isolation_source(strains: QuerySet[Strain], text: str) -> QuerySet[Strain]:
    """The isolation source contains the text, ignoring case ("soil" finds "forest soil")."""
    text = " ".join(text.split())
    if not text:
        return strains
    return strains.filter(isolation_source__icontains=text)


def from_depositor(strains: QuerySet[Strain], depositor: Depositor) -> QuerySet[Strain]:
    """Strains accepted from a deposit of the depositor (Deposit.strain, one to one)."""
    return strains.filter(deposit__depositor=depositor)


def with_distributable_vials(strains: QuerySet[Strain], distributable: bool) -> QuerySet[Strain]:
    """Strains with at least one vial that may go out, or with none (distributable=false)."""
    has = Exists(distributable_vials().filter(batch__strain=OuterRef("pk")))
    return strains.filter(has) if distributable else strains.exclude(has)


class Disagreement(StrEnum):
    """How a strain's classification can disagree with the official lists (#169)."""

    # An entry that matches the strain's taxon names a restriction the strain does not carry.
    RESTRICTION_MISSING = "restriction_missing"
    # The strain carries a restriction of a kind whose list names no matching entry.
    RESTRICTION_UNLISTED = "restriction_unlisted"
    # An entry of annex 7 states another risk group than the strain's.
    RISK_GROUP_DIFFERS = "risk_group_differs"


# The values the API answers with, for its ChoiceField: an enum class is not choices.
DISAGREEMENTS = [found.value for found in Disagreement]


@dataclass(frozen=True)
class Finding:
    """One disagreement of one strain, with the entry it was read in where there is one."""

    disagreement: str
    restriction_kind: str
    entry: RegulatoryListEntry | None
    # The reason in words the collection recorded for the strain's group, on a group that
    # differs from the entry's: a case a person accepted, with the reason to read.
    accepted_because: str = ""


@dataclass(frozen=True)
class StrainFindings:
    strain: Strain
    findings: list[Finding]


def list_findings(strain: Strain, entries: list[RegulatoryListEntry]) -> list[Finding]:
    """Where one strain's classification disagrees with the official lists (#169).

    The one definition. `entries` are the entries of the current readings that match the
    strain's taxon (biosafety.selectors.entries_for), and `strain.active_restrictions` the
    restrictions it carries now. Three ways to disagree, in this order:

    - an entry names a restriction of a kind the strain does not carry,
    - the strain carries a restriction of a kind whose list names no matching entry,
    - an entry of annex 7 of government order 361/2007 Sb. states another group than the
      strain's, either way round.

    A GMO is on no list (biosafety.selectors.LIST_OF_KIND), so a GMO restriction is never
    unlisted. Nothing here decides anything: a disagreement is a question for a person, because
    the taxon may be wrong, an annex names genera where a collection holds species, and an agent
    annex 7 does not list is not thereby group 1.
    """
    # The prefetch of strain_list, by its to_attr: the restrictions in force, no query.
    active: list[StrainRestriction] = vars(strain)["active_restrictions"]
    held = {restriction.kind for restriction in active}
    named = {entry.restriction_kind for entry in entries if entry.restriction_kind}
    findings = [
        Finding(Disagreement.RESTRICTION_MISSING, entry.restriction_kind, entry)
        for entry in entries
        if entry.restriction_kind and entry.restriction_kind not in held
    ]
    findings += [
        Finding(Disagreement.RESTRICTION_UNLISTED, kind, None)
        for kind in sorted((held & biosafety_lists.LIST_OF_KIND.keys()) - named)
    ]
    findings += [
        Finding(Disagreement.RISK_GROUP_DIFFERS, "", entry, strain.risk_group_basis)
        for entry in entries
        if entry.risk_group is not None and entry.risk_group != strain.risk_group
    ]
    return findings


def list_disagreements(*, access: Access, lab: Lab) -> list[StrainFindings]:
    """Every strain of the lab in the collection whose classification disagrees with the
    official lists, in the order of the strain list (#169).

    Computed, never stored, so it follows a reclassification, a restriction added or ended, a
    risk group changed and a new reading of a list with nothing to refresh and nothing to
    recompute. Four queries whatever the number of strains: the strains, the restrictions they
    carry, the names of their taxa and the entries that match any of those names.

    A deaccessioned strain is left out: its classification is the history of a strain that is no
    longer held (#20).
    """
    strains = list(in_collection(strain_list(access=access, lab=lab)))
    entries = biosafety_lists.entries_for(strain.taxon for strain in strains)
    found = (
        StrainFindings(strain, list_findings(strain, entries.get(strain.taxon_id, [])))
        for strain in strains
    )
    return [row for row in found if row.findings]

"""Reads of strains. Every one takes the access object, so the lab scope is in the signature."""

from django.db.models import Exists, F, OuterRef, Prefetch, Q, QuerySet

from cultures.biosafety.models import RestrictionKind
from cultures.deposits.models import Depositor
from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.taxonomy.models import Taxon
from cultures.taxonomy.selectors import taxon_and_below

from .models import (
    RestrictionEndProposal,
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


def strain_list(*, access: Access, lab: Lab) -> QuerySet[Strain]:
    """The strains of one lab the user may view, by accession number (numbered first). Every
    status: the list's filter leaves out the deaccessioned ones unless asked (filters)."""
    return (
        Strain.objects.for_access(access, Perm.VIEW_STRAINS)
        .filter(lab=lab)
        .select_related("taxon")
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
    whether the strain is regulated, and the open proposal to deaccession it (#20)."""
    history = (
        strain_list(access=access, lab=lab)
        .select_related("growth_medium")
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
    return history.prefetch_related(
        # At most one is open (a unique index).
        Prefetch(
            "deaccession_proposals",
            queryset=StrainDeaccessionProposal.objects.filter(
                confirmed_at__isnull=True, withdrawn_at__isnull=True
            ),
            to_attr="open_deaccession_proposals",
        )
    ).prefetch_related(
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

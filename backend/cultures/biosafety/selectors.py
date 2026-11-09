"""Reads of the lab's permits, and of the official lists (#169).

Every read of a lab's rows takes the access object, so the lab scope is part of the signature.
The lists have no lab: every signed-in user reads them, like the taxonomy (ADR 0008, D4).
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from django.db.models import (
    Case,
    CharField,
    DateField,
    F,
    IntegerField,
    Q,
    QuerySet,
    Value,
    When,
)
from django.db.models.functions import Cast, Least

from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.taxonomy.models import Taxon

from . import lists
from .models import (
    RISK_GROUP_LIST,
    LabAuthorisation,
    ListCode,
    MatchScope,
    RegulatoryListEntry,
    RestrictionKind,
)
from .policy import EXPIRES_SOON_DAYS


class Standing(StrEnum):
    """Where a permit stands on a day, first match wins (policy.valid_on is the rule)."""

    ENDED = "ended"  # ended_on reached: revoked, surrendered or entered in error
    EXPIRED = "expired"  # the last valid day passed
    NOT_YET_VALID = "not_yet_valid"  # valid_from still ahead
    EXPIRES_SOON = "expires_soon"  # valid, its last valid day within EXPIRES_SOON_DAYS
    VALID = "valid"


# The screen's order: what a manager must act on first, then what holds, then the history.
_RANK = {
    Standing.EXPIRES_SOON: 0,
    Standing.VALID: 1,
    Standing.NOT_YET_VALID: 2,
    Standing.EXPIRED: 3,
    Standing.ENDED: 3,
}


def permit_list(*, access: Access, lab: Lab, today: date) -> QuerySet[LabAuthorisation]:
    """Every permit of one lab, ended ones included, each with its `standing` on `today` (a
    Czech day, policy.permit_today) and its `last_valid_day` (the expiry, or the day before an
    early end, whichever comes first; empty when neither is set). Empty unless the user may
    read the lab's permits.

    Order: expiring soon, then valid, both by the last valid day (none stated last); then not
    yet valid by start; then expired and ended, the most recent first.
    """
    horizon = today + timedelta(days=EXPIRES_SOON_DAYS)
    # ended_on is the first invalid day, so the day before it is the last valid one.
    day_before_end = Cast(F("ended_on") - timedelta(days=1), DateField())
    standing = Case(
        When(Q(ended_on__lte=today), then=Value(Standing.ENDED.value)),
        When(Q(expires_on__lt=today), then=Value(Standing.EXPIRED.value)),
        When(Q(valid_from__gt=today), then=Value(Standing.NOT_YET_VALID.value)),
        When(
            Q(expires_on__lte=horizon) | Q(ended_on__lte=horizon + timedelta(days=1)),
            then=Value(Standing.EXPIRES_SOON.value),
        ),
        default=Value(Standing.VALID.value),
        output_field=CharField(),
    )
    rank = Case(
        *(When(standing=value.value, then=Value(n)) for value, n in _RANK.items()),
        output_field=IntegerField(),
    )
    current = Q(rank__lte=1)
    return (
        LabAuthorisation.objects.for_access(access, Perm.VIEW_LAB_PERMITS)
        .filter(lab=lab)
        # PostgreSQL's LEAST skips NULLs: either date alone, or NULL when both are.
        .annotate(
            standing=standing,
            last_valid_day=Least("expires_on", day_before_end, output_field=DateField()),
        )
        .annotate(rank=rank)
        .order_by(
            "rank",
            Case(When(current, then=F("last_valid_day"))).asc(nulls_last=True),
            Case(When(rank=2, then=F("valid_from"))).asc(),
            Case(When(rank=3, then=F("last_valid_day"))).desc(nulls_last=True),
            "kind",
            "pk",
        )
    )


# Which official list holds the entries a restriction of each kind names (#169). A GMO is on no
# list: its reference is the notification or permit of act 78/2004 Sb.
LIST_OF_KIND: dict[str, str] = {
    RestrictionKind.CZ_VRAT: ListCode.CZ_474_2002,
    RestrictionKind.CZ_RAT: ListCode.CZ_474_2002,
    RestrictionKind.DUAL_USE: ListCode.EU_2021_821_ANNEX_I,
    RestrictionKind.QUARANTINE_PEST: ListCode.EU_2019_2072_ANNEX_II,
}
# The kinds whose reference must be an entry of the list: the dual-use entry codes are the
# annex's own ("1C351.c"), so a reference that is not one of them is a mistake. A VRAT, a RAT
# and a quarantine pest are referred to by the words of their annex, which the app does not
# own, so an entry is attached when the reference matches one and not demanded.
ENTRY_REQUIRED: frozenset[str] = frozenset({RestrictionKind.DUAL_USE})
# The Annex I entries of Regulation (EU) 2021/821 that name an organism: 1C351.a (human and
# zoonotic pathogens), 1C351.c (bacteria), 1C351.e (fungi) and 1C354 (plant pathogens). The
# other entries of 1C351 are toxins and 1C353 genetic elements, which decree 474/2002 Sb.
# lists in its own parts and not by the same name.
DUAL_USE_ORGANISM = re.compile(r"^(1C351\.(a|c|e)(\.|$)|1C354(\.|$))")


def list_entry(kind: str, reference: str) -> RegulatoryListEntry | None:
    """The entry of the current reading of the kind's list whose code is `reference`, or None.

    One query, and no lock: a list is never edited, and a new reading is loaded by a command
    (biosafety.lists), so the entry a caller resolves stays the entry it wrote.
    """
    code = LIST_OF_KIND.get(kind)
    if code is None:
        return None
    found: RegulatoryListEntry | None = (
        RegulatoryListEntry.objects.filter(list__code=code, list__is_current=True, code=reference)
        .select_related("list")
        .first()
    )
    return found


def also_a_cz_agent(entry: RegulatoryListEntry) -> RegulatoryListEntry | None:
    """The entry of decree 474/2002 Sb. that names the same organism as this dual-use entry.

    #169, the last box: an Annex I entry of 1C351.a, 1C351.c, 1C351.e or 1C354 that decree
    474/2002 Sb. also lists is a highly risky agent (VRAT, annex 1) or a risky one (annex 2),
    and the strain must carry that restriction as well. The two entries are the same organism
    when they derive the same scientific name at the same scope (biosafety.lists.match_of);
    nothing matches by substring, and an entry with no derived name pairs with nothing.
    """
    if not entry.match_name or not DUAL_USE_ORGANISM.match(entry.code):
        return None
    found: RegulatoryListEntry | None = (
        RegulatoryListEntry.objects.filter(
            list__code=ListCode.CZ_474_2002,
            list__is_current=True,
            match_name=entry.match_name,
            match_scope=entry.match_scope,
        )
        .exclude(restriction_kind="")
        .order_by("restriction_kind", "pk")
        .first()
    )
    return found


@dataclass(frozen=True)
class MatchNames:
    """The names a taxon is matched against (#169): whole names, and the genus of each."""

    exact: frozenset[str]
    genera: frozenset[str]


def match_names_for(taxa: Iterable[Taxon]) -> dict[int, MatchNames]:
    """The names each of these taxa is matched against, by taxon id, in one query (#169).

    The one rule, for one taxon and for a thousand: the taxon's own name, the name of its
    accepted taxon when it is a synonym, and the names of every synonym of that accepted taxon,
    because one organism carries the same classification under each (ADR 0008, D4). The genus
    names are the first word of each, so a genus-wide entry of a list reaches a species of that
    genus.
    """
    wanted = {taxon.pk: taxon.accepted_id or taxon.pk for taxon in taxa}
    if not wanted:
        return {}
    roots = set(wanted.values())
    own: dict[int, str] = {}
    of_root: dict[int, set[str]] = defaultdict(set)
    rows = Taxon.objects.filter(
        Q(pk__in=roots | set(wanted)) | Q(accepted_id__in=roots)
    ).values_list("pk", "accepted_id", "name")
    for pk, accepted_id, name in rows:
        own[pk] = name
        of_root[accepted_id or pk].add(name)
    found: dict[int, MatchNames] = {}
    for pk, root in wanted.items():
        whole = of_root[root] | {own[pk]}
        exact = {lists.normalised(name) for name in whole}
        found[pk] = MatchNames(frozenset(exact), frozenset(name.split(" ")[0] for name in exact))
    return found


def match_names(taxon: Taxon) -> tuple[set[str], set[str]]:
    """The names one taxon is matched against, and the genus names of each (#169)."""
    found = match_names_for([taxon])[taxon.pk]
    return set(found.exact), set(found.genera)


def matching(names: MatchNames) -> Q:
    """Which entries match these names, in SQL (#169): an entry of scope `exact` on one of the
    whole names, an entry of scope `genus` on the genus of one of them. Never a part of a name,
    and an entry with no name to match reaches nothing, because it has no scope either."""
    return Q(match_scope=MatchScope.EXACT, match_name__in=sorted(names.exact)) | Q(
        match_scope=MatchScope.GENUS, match_name__in=sorted(names.genera)
    )


def matches(entry: RegulatoryListEntry, names: MatchNames) -> bool:
    """The same question in Python, for a read that fetched the entries of many taxa at once
    (`entries_for`). A test compares it with `matching` on every entry of every list."""
    if entry.match_scope == MatchScope.EXACT:
        return entry.match_name in names.exact
    if entry.match_scope == MatchScope.GENUS:
        return entry.match_name in names.genera
    return False


def list_matches(taxon: Taxon) -> QuerySet[RegulatoryListEntry]:
    """The entries of the current readings of the official lists that match a taxon (#169).

    A suggestion, never a classification: a person confirms one with a reason, through the
    services. Matching is `matching` above: whole names only, never a part of one.

    Two queries, with each entry's list for its source and version.
    """
    return (
        RegulatoryListEntry.objects.filter(
            matching(match_names_for([taxon])[taxon.pk]), list__is_current=True
        )
        .select_related("list")
        .order_by("list__code", "code", "pk")
    )


def entries_for(taxa: Iterable[Taxon]) -> dict[int, list[RegulatoryListEntry]]:
    """What the current readings of the lists say about each of these taxa, by taxon id (#169).

    `list_matches` for one taxon, for many at once: two queries whatever the number of taxa, one
    for the names and one for the entries of the union of them, then each entry placed under
    every taxon it matches, in the order `list_matches` gives.
    """
    names = match_names_for(taxa)
    if not names:
        return {}
    exact = {name for found in names.values() for name in found.exact}
    genera = {name for found in names.values() for name in found.genera}
    entries = list(
        RegulatoryListEntry.objects.filter(
            matching(MatchNames(frozenset(exact), frozenset(genera))), list__is_current=True
        )
        .select_related("list")
        .order_by("list__code", "code", "pk")
    )
    return {pk: [e for e in entries if matches(e, found)] for pk, found in names.items()}


def risk_group_entries() -> QuerySet[RegulatoryListEntry]:
    """The entries a risk group may rest on (#169): the entries of the current reading of annex
    7 of government order 361/2007 Sb. that state a group.

    No lab and no access object: the lists are law, and every signed-in user reads them. The
    entries of the other three lists state no risk group, and a reading that was replaced states
    nothing any more, so neither is here.
    """
    return RegulatoryListEntry.objects.filter(
        list__code=RISK_GROUP_LIST, list__is_current=True, risk_group__isnull=False
    ).select_related("list")


def states_risk_group(entry: RegulatoryListEntry, risk_group: int) -> bool:
    """Whether the entry is one of the above and states that very group (#169).

    The one definition the service and the trigger of migration `strains/0018` both ask: a basis
    that points at a list entry points at an entry of the current annex 7 stating the group
    being recorded, and at nothing else.
    """
    return (
        entry.list.code == RISK_GROUP_LIST
        and entry.list.is_current
        and entry.risk_group == risk_group
    )

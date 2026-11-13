"""Where a strain's classification disagrees with the official lists, for the managers (#169).

Three disagreements: an entry names a restriction the strain does not carry, the strain carries
one of a kind no matching entry names, and an entry of annex 7 of government order 361/2007 Sb.
states another risk group. Each is computed at the read, so a reclassification and a new reading
of a list change the answer with nothing written.

The strains are of invented taxa, or of a taxon named after an entry the test reads out of the
lists the app holds, so no test here states a legal fact about a real organism.
"""

from typing import Any

import pytest

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.biosafety.models import (
    AuthorisationKind,
    ListCode,
    MatchScope,
    RegulatoryList,
    RegulatoryListEntry,
    RestrictionKind,
)
from cultures.biosafety.selectors import MatchNames, entries_for, list_matches, matching
from cultures.core.testing import QueryBaseline, logged_in
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import ROLE_PERMS, Perm, Role
from cultures.strains import services
from cultures.strains.models import DeaccessionCause, Strain
from cultures.strains.selectors import Disagreement, list_disagreements
from cultures.strains.services import Deaccession, RestrictionInput
from cultures.taxonomy.models import Rank, Taxon
from cultures.taxonomy.tests.conftest import make_taxon
from cultures.users.models import User

from .conftest import GMO, LAB_ID, VRAT, MakeStrain, make_permit

pytestmark = pytest.mark.django_db

URL = f"/api/v1/labs/{LAB_ID}/strains/list-disagreements/"
Rows = dict[str, list[tuple[str, str, str]]]


def an_entry(list_code: str, **filters: Any) -> RegulatoryListEntry:
    """An entry of a list the app holds, with a name to match. Read out of the data, never
    written down here: the test needs a real entry, not a real organism."""
    found = (
        RegulatoryListEntry.objects.filter(
            list__code=list_code,
            list__is_current=True,
            match_scope=MatchScope.EXACT,
            **filters,
        )
        .exclude(match_name="")
        .order_by("code")
        .first()
    )
    assert found is not None, f"no exact entry of {list_code} matching {filters}"
    return found


def an_agreeable_entry() -> tuple[RegulatoryListEntry, list[RegulatoryListEntry]]:
    """An entry of decree 474/2002 Sb. listed as a risky agent whose name reaches only that
    entry and entries of annex 7 stating one group of 2 or 3, with everything its name reaches.

    A strain of that taxon can be accessioned one group below and then brought in line by one
    person, so the test needs neither a second person nor a permit. Most agents of the decree
    are in annex 7 as well, so an entry whose name reaches nothing else does not exist.
    """
    for entry in (
        RegulatoryListEntry.objects.filter(
            list__code=ListCode.CZ_474_2002,
            list__is_current=True,
            match_scope=MatchScope.EXACT,
            restriction_kind=RestrictionKind.CZ_RAT,
        )
        .exclude(match_name="")
        .order_by("code")
    ):
        # The names a taxon called after this entry is matched against: the one name, and its
        # genus. The same predicate the reads use, so what it reaches is what they reach.
        names = MatchNames(
            frozenset({entry.match_name}), frozenset({entry.match_name.split(" ")[0]})
        )
        reached = list(
            RegulatoryListEntry.objects.filter(matching(names), list__is_current=True)
            .select_related("list")
            .order_by("list__code", "code", "pk")
        )
        kinds = {found.restriction_kind for found in reached if found.restriction_kind}
        groups = {found.risk_group for found in reached if found.risk_group is not None}
        if kinds == {RestrictionKind.CZ_RAT} and groups in ({2}, {3}):
            return entry, reached
    raise AssertionError("no risky agent of the decree is one a strain can fully agree with")


def taxon_of(entry: RegulatoryListEntry) -> Taxon:
    """A taxon whose name is the one the entry derives, under its genus."""
    name = entry.match_name.capitalize()
    genus = Taxon.objects.filter(name=name.split(" ")[0], rank=Rank.GENUS).first() or make_taxon(
        name.split(" ")[0], Rank.GENUS
    )
    return Taxon.objects.filter(name=name).first() or make_taxon(name, Rank.SPECIES, genus)


def rows(user: User, lab: Lab) -> Rows:
    """The findings per accession number, as (disagreement, restriction kind, entry code)."""
    return {
        row.strain.accession_number or "": [
            (
                found.disagreement,
                found.restriction_kind,
                "" if found.entry is None else found.entry.code,
            )
            for found in row.findings
        ]
        for row in list_disagreements(access=access_for(user), lab=lab)
    }


def record(user: User, strain: Strain, restriction: RestrictionInput) -> None:
    with audit_context(channel=Channel.API, actor=user, request_id="req-record"):
        services.strain_restriction_add(
            access=access_for(user),
            strain=strain,
            restriction=restriction,
            reason="Read in the official list.",
        )


# What disagrees.


@pytest.mark.rule("R-MATCH-02")
def test_an_entry_that_names_a_restriction_the_strain_does_not_carry_is_listed(
    make_strain: MakeStrain, manager: User, lab: Lab
) -> None:
    entry = an_entry(ListCode.CZ_474_2002)
    strain = make_strain(taxon=taxon_of(entry))
    found = rows(manager, lab)[strain.accession_number or ""]
    assert (Disagreement.RESTRICTION_MISSING, entry.restriction_kind, entry.code) in found


@pytest.mark.rule("R-MATCH-02")
def test_a_restriction_of_a_kind_no_matching_entry_names_is_listed(
    make_strain: MakeStrain, manager: User, lab: Lab
) -> None:
    """The invented taxon is on no list, so the restriction rests on something the lists do not
    say. A question for a person, not a mistake: the taxon itself may be wrong."""
    make_permit(lab, AuthorisationKind.CZ_VRAT)
    strain = make_strain(restrictions=[VRAT])
    assert rows(manager, lab)[strain.accession_number or ""] == [
        (Disagreement.RESTRICTION_UNLISTED, RestrictionKind.CZ_VRAT, "")
    ]


@pytest.mark.rule("R-MATCH-02")
def test_a_gmo_restriction_is_never_unlisted(
    make_strain: MakeStrain, manager: User, lab: Lab
) -> None:
    """A GMO is on no official list: its reference is the notification of act 78/2004 Sb., so no
    entry is expected to name it."""
    make_strain(restrictions=[GMO])
    assert rows(manager, lab) == {}


@pytest.mark.rule("R-MATCH-02")
def test_an_entry_of_annex_7_that_states_another_group_is_listed(
    make_strain: MakeStrain, manager: User, lab: Lab
) -> None:
    entry = an_entry(ListCode.CZ_361_2007_ANNEX_7, risk_group=2)
    strain = make_strain(taxon=taxon_of(entry), risk_group=1)
    found = rows(manager, lab)[strain.accession_number or ""]
    assert (Disagreement.RISK_GROUP_DIFFERS, "", entry.code) in found


@pytest.mark.rule("R-MATCH-02", "R-RISK-10")
def test_a_group_that_differs_carries_the_reason_the_collection_recorded(
    make_strain: MakeStrain, manager: User
) -> None:
    entry = an_entry(ListCode.CZ_361_2007_ANNEX_7, risk_group=2)
    strain = make_strain(taxon=taxon_of(entry), risk_group=1)
    body = logged_in(manager).get(URL).json()
    row = next(
        r for r in body["results"] if r["strain"]["accession_number"] == strain.accession_number
    )
    found = next(f for f in row["findings"] if f["disagreement"] == Disagreement.RISK_GROUP_DIFFERS)
    assert found["accepted_because"] == strain.risk_group_basis != ""
    others = [f for f in row["findings"] if f["disagreement"] != Disagreement.RISK_GROUP_DIFFERS]
    assert all(f["accepted_because"] == "" for f in others)


@pytest.mark.rule("R-MATCH-02")
def test_a_strain_the_lists_say_nothing_about_is_not_listed(
    make_strain: MakeStrain, manager: User, lab: Lab
) -> None:
    make_strain()
    assert rows(manager, lab) == {}


# Computed, not stored.


@pytest.mark.rule("R-MATCH-02")
def test_recording_everything_the_lists_say_takes_the_strain_off_the_list(
    make_strain: MakeStrain, manager: User, curator: User, lab: Lab
) -> None:
    """Both directions on one strain: accessioned against what its entries say it is listed,
    and once the record says the same it is gone, with nothing written to say so."""
    entry, reached = an_agreeable_entry()
    group = next(found.risk_group for found in reached if found.risk_group is not None)
    # One group below what the annex states, so bringing it in line is a raise of one step and
    # one person's (R-RISK-03, R-RISK-08).
    strain = make_strain(taxon=taxon_of(entry), risk_group=group - 1)
    assert strain.accession_number in rows(manager, lab)
    record(curator, strain, RestrictionInput(RestrictionKind.CZ_RAT, entry.code))
    with audit_context(channel=Channel.API, actor=curator, request_id="req-group"):
        services.strain_set_risk_group(
            access=access_for(curator),
            strain=strain,
            risk_group=group,
            basis="Read in annex 7 of government order 361/2007 Sb.",
            reason="Brought in line with the annex.",
        )
    assert rows(manager, lab) == {}


@pytest.mark.rule("R-MATCH-02")
def test_a_reading_that_was_replaced_says_nothing_any_more(
    make_strain: MakeStrain, manager: User, lab: Lab
) -> None:
    entry = an_entry(ListCode.CZ_474_2002)
    strain = make_strain(taxon=taxon_of(entry))
    number = strain.accession_number or ""
    codes = [found[2] for found in rows(manager, lab)[number]]
    assert entry.code in codes
    # The loader makes a new reading current and takes the flag off the one before it; the list
    # rows are on no audited table, so a test may do that half of it directly.
    RegulatoryList.objects.filter(pk=entry.list_id).update(is_current=False)
    after = rows(manager, lab).get(number, [])
    assert entry.code not in [found[2] for found in after]


@pytest.mark.rule("R-MATCH-02")
def test_a_strain_that_left_the_collection_is_not_listed(
    make_strain: MakeStrain, manager: User, curator: User, lab: Lab
) -> None:
    entry = an_entry(ListCode.CZ_474_2002)
    strain = make_strain(taxon=taxon_of(entry))
    assert strain.accession_number in rows(manager, lab)
    with audit_context(channel=Channel.API, actor=curator, request_id="req-leave"):
        services.strain_deaccession(
            access=access_for(curator),
            strain=strain,
            data=Deaccession(cause=DeaccessionCause.NON_VIABLE, reason="No viable vial left."),
        )
    assert rows(manager, lab) == {}


# The lab-wide read and the strain page read the lists the same way.


@pytest.mark.rule("R-MATCH-02")
def test_the_managers_read_matches_the_suggestions_of_each_strain_page(
    exempli: Taxon, fictivibrio: Taxon, mockia: Taxon
) -> None:
    """`entries_for` asks in Python (`matches`) what `list_matches` asks in SQL (`matching`).
    Remove either and these pairs disagree."""
    named = taxon_of(an_entry(ListCode.CZ_474_2002))
    group = taxon_of(an_entry(ListCode.CZ_361_2007_ANNEX_7))
    taxa = [exempli, fictivibrio, mockia, named, group]
    bulk = entries_for(taxa)
    for taxon in taxa:
        assert [e.pk for e in bulk[taxon.pk]] == [e.pk for e in list_matches(taxon)], taxon.name


# Who reads it.


@pytest.mark.rule("R-MATCH-02")
def test_only_a_manager_reads_the_list(
    make_strain: MakeStrain, team: dict[Role, User], outsider: User
) -> None:
    make_strain(taxon=taxon_of(an_entry(ListCode.CZ_474_2002)))
    for role, user in team.items():
        wanted = 200 if Perm.VIEW_LIST_DISAGREEMENTS in ROLE_PERMS[role] else 403
        assert logged_in(user).get(URL).status_code == wanted, role
    assert logged_in(outsider).get(URL).status_code == 404


@pytest.mark.rule("R-MATCH-02")
def test_the_api_names_the_strain_and_every_disagreement(
    make_strain: MakeStrain, manager: User
) -> None:
    entry = an_entry(ListCode.CZ_474_2002)
    strain = make_strain(taxon=taxon_of(entry))
    answer = logged_in(manager).get(URL)
    assert answer.status_code == 200, answer.content
    body = answer.json()
    assert body["count"] == 1
    row = body["results"][0]
    assert row["strain"]["accession_number"] == strain.accession_number
    found = next(f for f in row["findings"] if f["entry"] and f["entry"]["code"] == entry.code)
    assert found["disagreement"] == Disagreement.RESTRICTION_MISSING
    assert found["restriction_kind"] == entry.restriction_kind
    assert found["entry"]["version"] == entry.list.version


@pytest.mark.rule("R-MATCH-02")
def test_the_read_costs_the_same_whatever_the_number_of_strains(
    make_strain: MakeStrain, manager: User, query_baseline: QueryBaseline
) -> None:
    taxon = taxon_of(an_entry(ListCode.CZ_474_2002))
    for _ in range(4):
        make_strain(taxon=taxon)
    client = logged_in(manager)
    # Session, user, memberships, the lab, the strains, the restrictions they carry, the names
    # of their taxa and the entries of every name.
    with query_baseline("strain_list_disagreements"):
        answer = client.get(URL)
    assert answer.json()["count"] == 4

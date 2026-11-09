"""The official lists suggest, and nothing more (#169).

What matches a taxon: its own name, the name of its accepted taxon, the name of any synonym of
that taxon, and a genus-wide entry of the genus of one of those. Never a part of a name.

The taxa are invented (Testella, Mockia, Fictivibrio), so no test states a legal fact about a
real organism. They match nothing in the real lists, so the matching itself is proved against
entries the tests read out of the lists the app holds, by their own derived names.
"""

import pytest

from cultures.biosafety.models import ListCode, MatchScope, RegulatoryList, RegulatoryListEntry
from cultures.biosafety.selectors import list_matches, match_names
from cultures.core.testing import logged_in
from cultures.strains.models import Strain
from cultures.taxonomy.models import Rank, Taxon
from cultures.taxonomy.tests.conftest import make_synonym, make_taxon
from cultures.users.models import User

from .conftest import LAB_ID, MakeStrain

pytestmark = pytest.mark.django_db

URL = f"/api/v1/labs/{LAB_ID}/strains/{{}}/list-matches/"


def an_entry(
    scope: MatchScope, list_code: str = ListCode.CZ_361_2007_ANNEX_7
) -> RegulatoryListEntry:
    """An entry of a list the app holds, with a name to match at this scope. Taken from the
    data, never written down here: the test needs a real entry, not a real organism."""
    found = (
        RegulatoryListEntry.objects.filter(
            list__code=list_code, list__is_current=True, match_scope=scope
        )
        .exclude(match_name="")
        .order_by("code")
        .first()
    )
    assert found is not None, f"no {scope} entry in {list_code}"
    return found


def taxon_named(name: str, rank: Rank = Rank.SPECIES) -> Taxon:
    return make_taxon(name.capitalize(), rank)


@pytest.mark.rule("R-MATCH-01")
def test_an_exact_entry_matches_the_taxons_own_name(make_strain: MakeStrain) -> None:
    entry = an_entry(MatchScope.EXACT)
    genus, species = entry.match_name.split(" ")[0], entry.match_name
    taxon = make_taxon(
        species.capitalize(), Rank.SPECIES, make_taxon(genus.capitalize(), Rank.GENUS)
    )
    strain = make_strain(taxon=taxon)
    assert entry in list_matches(strain.taxon)


@pytest.mark.rule("R-MATCH-01")
def test_an_entry_of_a_genus_matches_a_species_of_it(make_strain: MakeStrain) -> None:
    entry = an_entry(MatchScope.GENUS)
    genus = make_taxon(entry.match_name.capitalize(), Rank.GENUS)
    taxon = make_taxon(f"{entry.match_name.capitalize()} ficta", Rank.SPECIES, genus)
    strain = make_strain(taxon=taxon)
    assert entry in list_matches(strain.taxon)


@pytest.mark.rule("R-MATCH-01")
def test_a_synonym_and_its_accepted_name_match_the_same_entries(make_strain: MakeStrain) -> None:
    entry = an_entry(MatchScope.EXACT)
    genus = make_taxon(entry.match_name.split(" ")[0].capitalize(), Rank.GENUS)
    accepted = make_taxon(entry.match_name.capitalize(), Rank.SPECIES, genus)
    synonym = make_synonym("Fictivibrio aliud", Rank.SPECIES, accepted)
    assert entry in list_matches(accepted)
    assert entry in list_matches(synonym)
    names, _ = match_names(synonym)
    assert {entry.match_name, "fictivibrio aliud"} <= names


@pytest.mark.rule("R-MATCH-01")
def test_a_part_of_a_name_matches_nothing(make_strain: MakeStrain) -> None:
    entry = an_entry(MatchScope.EXACT)
    cut = make_taxon(entry.match_name[: len(entry.match_name) - 2].capitalize(), Rank.SPECIES)
    longer = make_taxon(f"{entry.match_name.capitalize()}xx", Rank.SPECIES)
    assert entry not in list_matches(cut)
    assert entry not in list_matches(longer)


@pytest.mark.rule("R-MATCH-01")
def test_an_invented_taxon_matches_nothing(make_strain: MakeStrain, exempli: Taxon) -> None:
    assert not list_matches(exempli).exists()


@pytest.mark.rule("R-MATCH-01")
def test_a_reading_that_was_replaced_suggests_nothing() -> None:
    entry = an_entry(MatchScope.EXACT)
    # The loader makes a new reading current and takes the flag off the one before it; the rows
    # are on no audited table, so a test may do that half of it directly.
    RegulatoryList.objects.filter(pk=entry.list_id).update(is_current=False)
    genus = make_taxon(entry.match_name.split(" ")[0].capitalize(), Rank.GENUS)
    taxon = make_taxon(entry.match_name.capitalize(), Rank.SPECIES, genus)
    assert entry not in list_matches(taxon)


@pytest.mark.rule("R-MATCH-01")
def test_the_api_lists_what_the_lists_say_about_the_taxon(
    make_strain: MakeStrain, viewer: User
) -> None:
    entry = an_entry(MatchScope.EXACT)
    genus = make_taxon(entry.match_name.split(" ")[0].capitalize(), Rank.GENUS)
    taxon = make_taxon(entry.match_name.capitalize(), Rank.SPECIES, genus)
    strain: Strain = make_strain(taxon=taxon)
    answer = logged_in(viewer).get(URL.format(strain.public_id))
    assert answer.status_code == 200
    rows = {row["code"]: row for row in answer.json()["results"]}
    row = rows[entry.code]
    assert row["list"] == entry.list.code
    assert row["version"] == entry.list.version
    assert row["act"] == entry.list.act
    assert row["risk_group"] == entry.risk_group
    assert row["match_scope"] == MatchScope.EXACT
    assert row["restriction_kind"] == entry.restriction_kind
    assert row["suggests_act"] == ""  # only a dual-use entry names the act its annex was in


@pytest.mark.rule("R-MATCH-01")
def test_nobody_outside_the_lab_reads_the_suggestions(
    make_strain: MakeStrain, outsider: User
) -> None:
    strain = make_strain()
    assert logged_in(outsider).get(URL.format(strain.public_id)).status_code == 404

"""A taxon filter means the accepted taxa at and below it and the synonyms of each."""

import pytest

from cultures.taxonomy import selectors
from cultures.taxonomy.models import Rank, Taxon

from .conftest import make_synonym, make_taxon

pytestmark = pytest.mark.django_db


def below(taxon: Taxon) -> set[str]:
    return set(
        Taxon.objects.filter(pk__in=selectors.taxon_and_below(taxon)).values_list("name", flat=True)
    )


def test_a_genus_reaches_its_species_their_subspecies_and_their_synonyms(
    bacillus: Taxon, subtilis: Taxon, spizizenii: Taxon, vibrio_subtilis: Taxon, coli: Taxon
) -> None:
    assert below(bacillus) == {
        "Bacillus",
        "Bacillus subtilis",
        "Bacillus subtilis subsp. spizizenii",
        "Vibrio subtilis",
    }


def test_a_species_reaches_its_subspecies_and_synonyms_but_not_its_genus(
    bacillus: Taxon, subtilis: Taxon, spizizenii: Taxon, vibrio_subtilis: Taxon
) -> None:
    assert below(subtilis) == {
        "Bacillus subtilis",
        "Bacillus subtilis subsp. spizizenii",
        "Vibrio subtilis",
    }


def test_a_synonym_means_its_accepted_taxon(
    subtilis: Taxon, spizizenii: Taxon, vibrio_subtilis: Taxon
) -> None:
    assert below(vibrio_subtilis) == below(subtilis)


def test_a_synonym_of_a_subspecies_is_reached_from_the_genus(
    bacillus: Taxon, spizizenii: Taxon
) -> None:
    make_synonym("Bacillus spizizenii", Rank.SPECIES, spizizenii)
    assert "Bacillus spizizenii" in below(bacillus)


def test_the_walk_ends_on_a_cycle_made_outside_the_services(
    bacillus: Taxon, subtilis: Taxon
) -> None:
    Taxon.objects.filter(pk=bacillus.pk).update(parent=subtilis)  # ranks no longer fall
    assert below(bacillus) == {"Bacillus", "Bacillus subtilis"}


def search(text: str) -> list[str]:
    return list(
        selectors.taxon_search(selectors.taxon_list(), text=text).values_list("name", flat=True)
    )


def test_search_finds_names_containing_the_text_starting_ones_first(
    bacillus: Taxon, subtilis: Taxon, vibrio_subtilis: Taxon, coli: Taxon
) -> None:
    make_taxon("Paenibacillus", Rank.GENUS)
    assert search("bacillus") == ["Bacillus", "Bacillus subtilis", "Paenibacillus"]
    assert search("  SUBTILIS ") == ["Bacillus subtilis", "Vibrio subtilis"]
    assert search("") == [
        "Bacillus",
        "Bacillus subtilis",
        "Escherichia",
        "Escherichia coli",
        "Paenibacillus",
        "Vibrio subtilis",
    ]

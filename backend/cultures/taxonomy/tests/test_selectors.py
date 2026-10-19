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
    testella: Taxon, exempli: Taxon, alpha: Taxon, fictivibrio: Taxon, mockia: Taxon
) -> None:
    assert below(testella) == {
        "Testella",
        "Testella exempli",
        "Testella exempli subsp. alpha",
        "Fictivibrio exempli",
    }


def test_a_species_reaches_its_subspecies_and_synonyms_but_not_its_genus(
    testella: Taxon, exempli: Taxon, alpha: Taxon, fictivibrio: Taxon
) -> None:
    assert below(exempli) == {
        "Testella exempli",
        "Testella exempli subsp. alpha",
        "Fictivibrio exempli",
    }


def test_a_synonym_means_its_accepted_taxon(
    exempli: Taxon, alpha: Taxon, fictivibrio: Taxon
) -> None:
    assert below(fictivibrio) == below(exempli)


def test_a_synonym_of_a_subspecies_is_reached_from_the_genus(testella: Taxon, alpha: Taxon) -> None:
    make_synonym("Testella alpha", Rank.SPECIES, alpha)
    assert "Testella alpha" in below(testella)


def test_the_walk_ends_on_a_cycle_made_outside_the_services(
    testella: Taxon, exempli: Taxon
) -> None:
    Taxon.objects.filter(pk=testella.pk).update(parent=exempli)  # ranks no longer fall
    assert below(testella) == {"Testella", "Testella exempli"}


def search(text: str) -> list[str]:
    return list(
        selectors.taxon_search(selectors.taxon_list(), text=text).values_list("name", flat=True)
    )


def test_search_finds_names_containing_the_text_starting_ones_first(
    testella: Taxon, exempli: Taxon, fictivibrio: Taxon, mockia: Taxon
) -> None:
    make_taxon("Paratestella", Rank.GENUS)
    assert search("testella") == ["Testella", "Testella exempli", "Paratestella"]
    assert search("  EXEMPLI ") == ["Fictivibrio exempli", "Testella exempli"]
    assert search("") == [
        "Fictivibrio exempli",
        "Mockia",
        "Mockia vulgaris",
        "Paratestella",
        "Testella",
        "Testella exempli",
    ]

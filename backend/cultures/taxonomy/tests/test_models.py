"""The database refuses a broken taxonomy on its own, also when the services are skipped."""

from typing import Any

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from cultures.taxonomy.models import IdentifierSystem, Rank, Taxon, TaxonIdentifier, TaxonStatus

from .conftest import make_taxon

pytestmark = pytest.mark.django_db


def refused(constraint: str) -> Any:
    return pytest.raises(IntegrityError, match=constraint)


def test_the_same_name_authority_and_rank_twice_is_refused_ignoring_case(subtilis: Taxon) -> None:
    with refused("taxonomy_taxon_name_authority_rank_uniq"), transaction.atomic():
        make_taxon("BACILLUS SUBTILIS", Rank.SPECIES, authority="(Ehrenberg 1835) Cohn 1872")


def test_homonyms_differ_by_authority_or_rank(subtilis: Taxon) -> None:
    make_taxon("Bacillus subtilis", Rank.SPECIES, authority="Someone 1900")
    make_taxon("Bacillus subtilis", Rank.SUBSPECIES, authority="(Ehrenberg 1835) Cohn 1872")
    assert Taxon.objects.filter(name="Bacillus subtilis").count() == 3


@pytest.mark.parametrize("name", ["", " Bacillus", "Bacillus "])
def test_a_blank_or_untrimmed_name_is_refused(name: str) -> None:
    with refused("taxonomy_taxon_name_trimmed"), transaction.atomic():
        make_taxon(name, Rank.GENUS)


def test_an_unknown_rank_or_status_is_refused(bacillus: Taxon) -> None:
    with refused("taxonomy_taxon_rank_valid"), transaction.atomic():
        Taxon.objects.filter(pk=bacillus.pk).update(rank="tribe")
    with refused("taxonomy_taxon_accepted_iff_synonym"), transaction.atomic():
        Taxon.objects.filter(pk=bacillus.pk).update(status="doubtful")


def test_a_synonym_needs_its_accepted_taxon(bacillus: Taxon) -> None:
    with refused("taxonomy_taxon_accepted_iff_synonym"), transaction.atomic():
        Taxon.objects.filter(pk=bacillus.pk).update(status=TaxonStatus.SYNONYM)


def test_an_accepted_taxon_points_at_no_accepted_taxon(bacillus: Taxon, escherichia: Taxon) -> None:
    with refused("taxonomy_taxon_accepted_iff_synonym"), transaction.atomic():
        Taxon.objects.filter(pk=bacillus.pk).update(accepted=escherichia)


def test_a_synonym_has_no_parent(subtilis: Taxon, vibrio_subtilis: Taxon, bacillus: Taxon) -> None:
    with refused("taxonomy_taxon_synonym_has_no_parent"), transaction.atomic():
        Taxon.objects.filter(pk=vibrio_subtilis.pk).update(parent=bacillus)


def test_a_taxon_is_not_its_own_parent_or_accepted(bacillus: Taxon) -> None:
    with refused("taxonomy_taxon_not_its_own_parent_or_accepted"), transaction.atomic():
        Taxon.objects.filter(pk=bacillus.pk).update(parent=bacillus)
    with refused("taxonomy_taxon_not_its_own_parent_or_accepted"), transaction.atomic():
        Taxon.objects.filter(pk=bacillus.pk).update(status=TaxonStatus.SYNONYM, accepted=bacillus)


def test_a_taxon_with_children_or_synonyms_cannot_be_deleted(
    bacillus: Taxon, subtilis: Taxon, vibrio_subtilis: Taxon
) -> None:
    with pytest.raises(ProtectedError), transaction.atomic():
        bacillus.delete()
    with pytest.raises(ProtectedError), transaction.atomic():
        subtilis.delete()


def identifier(taxon: Taxon, system: IdentifierSystem, value: str) -> TaxonIdentifier:
    return TaxonIdentifier.objects.create(taxon=taxon, system=system, value=value)


def test_an_external_id_belongs_to_one_taxon(bacillus: Taxon, escherichia: Taxon) -> None:
    identifier(bacillus, IdentifierSystem.NCBI, "1386")
    with refused("taxonomy_taxonidentifier_system_value_uniq"), transaction.atomic():
        identifier(escherichia, IdentifierSystem.NCBI, "1386")
    identifier(escherichia, IdentifierSystem.MYCOBANK, "1386")  # the same value, another system


def test_a_taxon_has_one_id_per_system(bacillus: Taxon) -> None:
    identifier(bacillus, IdentifierSystem.NCBI, "1386")
    with refused("taxonomy_taxonidentifier_taxon_system_uniq"), transaction.atomic():
        identifier(bacillus, IdentifierSystem.NCBI, "1387")


@pytest.mark.parametrize(
    ("system", "value", "constraint"),
    [
        ("ncbi", "13a6", "taxonomy_taxonidentifier_ncbi_numeric"),
        ("lpsn", "a b", "taxonomy_taxonidentifier_value_no_space"),
        ("lpsn", "", "taxonomy_taxonidentifier_value_no_space"),
        ("gbif", "1", "taxonomy_taxonidentifier_system_valid"),
    ],
)
def test_a_malformed_external_id_is_refused(
    bacillus: Taxon, system: str, value: str, constraint: str
) -> None:
    with refused(constraint), transaction.atomic():
        TaxonIdentifier.objects.create(taxon=bacillus, system=system, value=value)


def test_a_taxon_without_any_external_id_is_fine(bacillus: Taxon) -> None:
    """A fungus or a newly described species may have none (ADR 0008, D4)."""
    assert bacillus.identifiers.count() == 0

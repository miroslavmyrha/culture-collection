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


def test_the_same_name_authority_and_rank_twice_is_refused_ignoring_case(exempli: Taxon) -> None:
    with refused("taxonomy_taxon_name_authority_rank_uniq"), transaction.atomic():
        make_taxon("TESTELLA EXEMPLI", Rank.SPECIES, authority="Doe 2001")


def test_homonyms_differ_by_authority_or_rank(exempli: Taxon) -> None:
    make_taxon("Testella exempli", Rank.SPECIES, authority="Someone 1900")
    make_taxon("Testella exempli", Rank.SUBSPECIES, authority="Doe 2001")
    assert Taxon.objects.filter(name="Testella exempli").count() == 3


@pytest.mark.parametrize("name", ["", " Testella", "Testella "])
def test_a_blank_or_untrimmed_name_is_refused(name: str) -> None:
    with refused("taxonomy_taxon_name_trimmed"), transaction.atomic():
        make_taxon(name, Rank.GENUS)


def test_an_unknown_rank_or_status_is_refused(testella: Taxon) -> None:
    with refused("taxonomy_taxon_rank_valid"), transaction.atomic():
        Taxon.objects.filter(pk=testella.pk).update(rank="tribe")
    with refused("taxonomy_taxon_accepted_iff_synonym"), transaction.atomic():
        Taxon.objects.filter(pk=testella.pk).update(status="doubtful")


def test_a_synonym_needs_its_accepted_taxon(testella: Taxon) -> None:
    with refused("taxonomy_taxon_accepted_iff_synonym"), transaction.atomic():
        Taxon.objects.filter(pk=testella.pk).update(status=TaxonStatus.SYNONYM)


def test_an_accepted_taxon_points_at_no_accepted_taxon(
    testella: Taxon, mockia_genus: Taxon
) -> None:
    with refused("taxonomy_taxon_accepted_iff_synonym"), transaction.atomic():
        Taxon.objects.filter(pk=testella.pk).update(accepted=mockia_genus)


def test_a_synonym_has_no_parent(exempli: Taxon, fictivibrio: Taxon, testella: Taxon) -> None:
    with refused("taxonomy_taxon_synonym_has_no_parent"), transaction.atomic():
        Taxon.objects.filter(pk=fictivibrio.pk).update(parent=testella)


def test_a_taxon_is_not_its_own_parent_or_accepted(testella: Taxon) -> None:
    with refused("taxonomy_taxon_not_its_own_parent_or_accepted"), transaction.atomic():
        Taxon.objects.filter(pk=testella.pk).update(parent=testella)
    with refused("taxonomy_taxon_not_its_own_parent_or_accepted"), transaction.atomic():
        Taxon.objects.filter(pk=testella.pk).update(status=TaxonStatus.SYNONYM, accepted=testella)


def test_a_taxon_with_children_or_synonyms_cannot_be_deleted(
    testella: Taxon, exempli: Taxon, fictivibrio: Taxon
) -> None:
    with pytest.raises(ProtectedError), transaction.atomic():
        testella.delete()
    with pytest.raises(ProtectedError), transaction.atomic():
        exempli.delete()


def identifier(taxon: Taxon, system: IdentifierSystem, value: str) -> TaxonIdentifier:
    return TaxonIdentifier.objects.create(taxon=taxon, system=system, value=value)


def test_an_external_id_belongs_to_one_taxon(testella: Taxon, mockia_genus: Taxon) -> None:
    identifier(testella, IdentifierSystem.NCBI, "900001")
    with refused("taxonomy_taxonidentifier_system_value_uniq"), transaction.atomic():
        identifier(mockia_genus, IdentifierSystem.NCBI, "900001")
    identifier(mockia_genus, IdentifierSystem.MYCOBANK, "900001")  # the same value, another system


def test_a_taxon_has_one_id_per_system(testella: Taxon) -> None:
    identifier(testella, IdentifierSystem.NCBI, "900001")
    with refused("taxonomy_taxonidentifier_taxon_system_uniq"), transaction.atomic():
        identifier(testella, IdentifierSystem.NCBI, "900002")


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
    testella: Taxon, system: str, value: str, constraint: str
) -> None:
    with refused(constraint), transaction.atomic():
        TaxonIdentifier.objects.create(taxon=testella, system=system, value=value)


def test_a_taxon_without_any_external_id_is_fine(testella: Taxon) -> None:
    """A fungus or a newly described species may have none (ADR 0008, D4)."""
    assert testella.identifiers.count() == 0

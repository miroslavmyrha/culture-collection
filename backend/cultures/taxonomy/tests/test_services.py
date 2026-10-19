"""Staff change the taxonomy only through the services: the rules across rows, one event each,
and a refusal that changes nothing and records nothing."""

from typing import Any

import pytest

from cultures.audit.context import AuditContext, MissingAuditContext
from cultures.audit.models import AuditEvent, RowChange
from cultures.taxonomy import services
from cultures.taxonomy.models import IdentifierSystem, Rank, Taxon, TaxonIdentifier, TaxonStatus
from cultures.taxonomy.services import TaxonFields, TaxonRuleBroken
from cultures.users.models import User

pytestmark = pytest.mark.django_db


def snapshot() -> tuple[list[Any], list[Any], int, int]:
    """Taxa, ids, events and row changes: a refusal leaves all four as they were."""
    return (
        list(Taxon.objects.order_by("pk").values()),
        list(TaxonIdentifier.objects.order_by("pk").values()),
        AuditEvent.objects.count(),
        RowChange.objects.count(),
    )


def refused(code: str, attr: str, call: Any) -> None:
    before = snapshot()
    with pytest.raises(TaxonRuleBroken) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == (code, attr)
    assert snapshot() == before


def test_staff_add_a_species_under_its_genus(
    as_staff: AuditContext, staff: User, testella: Taxon
) -> None:
    taxon = services.taxon_create(
        fields=TaxonFields(
            name=" Testella  cerea ",
            authority="Moe and Moe 1987",
            rank=Rank.SPECIES,
            parent=testella,
        )
    )
    assert (taxon.name, taxon.status, taxon.parent, taxon.accepted) == (
        "Testella cerea",
        TaxonStatus.ACCEPTED,
        testella,
        None,
    )
    event = AuditEvent.objects.get()
    assert (event.event_type, event.actor, event.subject_type, event.subject_id) == (
        "taxon_created",
        staff,
        "taxon",
        taxon.public_id,
    )
    assert (event.lab_id, event.strain_id) == (None, None)  # global: no lab, no strain
    assert event.changes == {
        "name": [None, "Testella cerea"],
        "authority": [None, "Moe and Moe 1987"],
        "rank": [None, "species"],
        "status": [None, "accepted"],
        "parent": [None, str(testella.public_id)],
        "accepted": [None, None],
    }


def test_a_synonym_points_at_its_accepted_name(as_staff: AuditContext, exempli: Taxon) -> None:
    synonym = services.taxon_create(
        fields=TaxonFields(
            name="Fictivibrio exempli", authority="Doe 1990", rank=Rank.SPECIES, accepted=exempli
        )
    )
    assert (synonym.status, synonym.accepted, synonym.parent) == (
        TaxonStatus.SYNONYM,
        exempli,
        None,
    )


def test_a_parent_ranks_above_its_child(as_staff: AuditContext, exempli: Taxon) -> None:
    refused(
        "invalid_taxon",
        "parent",
        lambda: services.taxon_create(
            fields=TaxonFields(name="Testella", authority="", rank=Rank.GENUS, parent=exempli)
        ),
    )
    refused(
        "invalid_taxon",
        "parent",
        lambda: services.taxon_create(
            fields=TaxonFields(name="Testella x", authority="", rank=Rank.SPECIES, parent=exempli)
        ),
    )


def test_a_synonym_is_neither_a_parent_nor_an_accepted_name(
    as_staff: AuditContext, fictivibrio: Taxon
) -> None:
    refused(
        "invalid_taxon",
        "parent",
        lambda: services.taxon_create(
            fields=TaxonFields(
                name="Fictivibrio exempli x", authority="", rank=Rank.SUBSPECIES, parent=fictivibrio
            )
        ),
    )
    refused(
        "invalid_taxon",
        "accepted",
        lambda: services.taxon_create(
            fields=TaxonFields(
                name="Testella globosa", authority="", rank=Rank.SPECIES, accepted=fictivibrio
            )
        ),
    )


def test_a_synonym_with_a_parent_is_refused(
    as_staff: AuditContext, testella: Taxon, exempli: Taxon
) -> None:
    refused(
        "invalid_taxon",
        "parent",
        lambda: services.taxon_create(
            fields=TaxonFields(
                name="Fictivibrio exempli",
                authority="",
                rank=Rank.SPECIES,
                parent=testella,
                accepted=exempli,
            )
        ),
    )


def test_a_duplicate_name_is_a_field_error(
    as_staff: AuditContext, exempli: Taxon, testella: Taxon
) -> None:
    refused(
        "unique",
        "name",
        lambda: services.taxon_create(
            fields=TaxonFields(
                name="testella exempli",
                authority="Doe 2001",
                rank=Rank.SPECIES,
                parent=testella,
            )
        ),
    )


def fields_of(taxon: Taxon, **changes: Any) -> TaxonFields:
    values: dict[str, Any] = {
        "name": taxon.name,
        "authority": taxon.authority,
        "rank": Rank(taxon.rank),
        "parent": taxon.parent,
        "accepted": taxon.accepted,
    }
    return TaxonFields(**{**values, **changes})


def test_staff_make_a_name_a_synonym(
    as_staff: AuditContext, testella: Taxon, mockia: Taxon
) -> None:
    other = Taxon.objects.create(
        name="Testella vulgaris", rank=Rank.SPECIES, parent=testella, status=TaxonStatus.ACCEPTED
    )
    updated = services.taxon_update(
        taxon=other, fields=fields_of(other, parent=None, accepted=mockia)
    )
    assert (updated.status, updated.accepted, updated.parent) == (TaxonStatus.SYNONYM, mockia, None)
    event = AuditEvent.objects.get()
    assert event.event_type == "taxon_changed"
    assert event.changes == {
        "status": ["accepted", "synonym"],
        "parent": [str(testella.public_id), None],
        "accepted": [None, str(mockia.public_id)],
    }


def test_a_taxon_with_children_does_not_become_a_synonym(
    as_staff: AuditContext, testella: Taxon, exempli: Taxon, mockia_genus: Taxon
) -> None:
    refused(
        "invalid_taxon",
        "accepted",
        lambda: services.taxon_update(
            taxon=testella, fields=fields_of(testella, accepted=mockia_genus)
        ),
    )


def test_a_taxon_with_synonyms_does_not_become_a_synonym(
    as_staff: AuditContext, exempli: Taxon, fictivibrio: Taxon, mockia: Taxon
) -> None:
    """No chains: the synonyms are pointed at the new accepted name first."""
    refused(
        "invalid_taxon",
        "accepted",
        lambda: services.taxon_update(
            taxon=exempli, fields=fields_of(exempli, parent=None, accepted=mockia)
        ),
    )


def test_a_rank_change_keeps_the_children_below(
    as_staff: AuditContext, testella: Taxon, exempli: Taxon
) -> None:
    refused(
        "invalid_taxon",
        "rank",
        lambda: services.taxon_update(
            taxon=testella, fields=fields_of(testella, rank=Rank.SPECIES)
        ),
    )


def test_a_taxon_is_not_its_own_synonym(as_staff: AuditContext, mockia_genus: Taxon) -> None:
    refused(
        "invalid_taxon",
        "accepted",
        lambda: services.taxon_update(
            taxon=mockia_genus, fields=fields_of(mockia_genus, accepted=mockia_genus)
        ),
    )


def test_a_rule_reads_the_committed_parent_not_the_one_passed(
    as_staff: AuditContext, testella: Taxon, mockia: Taxon
) -> None:
    """The caller's copy says accepted, the row says synonym (changed meanwhile): refused."""
    stale = Taxon.objects.get(pk=testella.pk)
    Taxon.objects.filter(pk=testella.pk).update(status=TaxonStatus.SYNONYM, accepted=mockia)
    refused(
        "invalid_taxon",
        "parent",
        lambda: services.taxon_create(
            fields=TaxonFields(name="Testella x", authority="", rank=Rank.SPECIES, parent=stale)
        ),
    )


def test_an_update_that_changes_nothing_records_nothing(
    as_staff: AuditContext, exempli: Taxon
) -> None:
    services.taxon_update(taxon=exempli, fields=fields_of(exempli, name=" Testella   exempli"))
    assert AuditEvent.objects.count() == 0


def test_staff_add_and_remove_an_external_id(as_staff: AuditContext, exempli: Taxon) -> None:
    added = services.taxon_identifier_add(
        taxon=exempli, system=IdentifierSystem.NCBI, value=" 900003 "
    )
    assert (added.system, added.value) == ("ncbi", "900003")
    services.taxon_identifier_remove(identifier=added)
    assert not TaxonIdentifier.objects.exists()
    events = list(
        AuditEvent.objects.order_by("pk").values_list("event_type", "subject_id", "changes")
    )
    assert events == [
        (
            "taxon_identifier_added",
            added.public_id,
            {
                "taxon": [None, str(exempli.public_id)],
                "system": [None, "ncbi"],
                "value": [None, "900003"],
            },
        ),
        (
            "taxon_identifier_removed",
            added.public_id,
            {
                "taxon": [str(exempli.public_id), None],
                "system": ["ncbi", None],
                "value": ["900003", None],
            },
        ),
    ]


def test_an_id_of_another_taxon_and_a_second_id_per_system_are_field_errors(
    as_staff: AuditContext, exempli: Taxon, mockia: Taxon
) -> None:
    services.taxon_identifier_add(taxon=exempli, system=IdentifierSystem.NCBI, value="900003")
    refused(
        "unique",
        "value",
        lambda: services.taxon_identifier_add(
            taxon=mockia, system=IdentifierSystem.NCBI, value="900003"
        ),
    )
    refused(
        "unique",
        "system",
        lambda: services.taxon_identifier_add(
            taxon=exempli, system=IdentifierSystem.NCBI, value="900004"
        ),
    )


def test_services_refuse_to_run_without_an_audit_context(testella: Taxon) -> None:
    with pytest.raises(MissingAuditContext):
        services.taxon_create(
            fields=TaxonFields(name="Testella x", authority="", rank=Rank.SPECIES, parent=testella)
        )
    assert Taxon.objects.count() == 1

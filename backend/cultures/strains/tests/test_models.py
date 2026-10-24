"""The database refuses a strain record that cannot be true, also when the services are
skipped: constraints for every invariant of one row, triggers for what may never change."""

from datetime import date
from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction
from django.db.models.functions import Now
from django.utils import timezone

from cultures.biosafety.models import RestrictionKind
from cultures.labs.models import Lab
from cultures.strains.models import (
    RestrictionEndProposal,
    Strain,
    StrainCounter,
    StrainIdentification,
    StrainRestriction,
    StrainStatus,
)
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .conftest import MakeStrain

pytestmark = pytest.mark.django_db


def refused(constraint: str) -> Any:
    return pytest.raises(IntegrityError, match=constraint)


def guarded(message: str) -> Any:
    """A guard trigger raises restrict_violation, which psycopg reports as an IntegrityError."""
    return pytest.raises((IntegrityError, InternalError), match=message)


def raw_end(row: StrainRestriction, proposer: User, confirmer: User, reason: str) -> None:
    """Ends a restriction in raw writes the way the guard allows (#105): a proposal, its
    confirmation by another person, and the end at that time with that reason."""
    now = timezone.now()
    proposal = RestrictionEndProposal.objects.create(
        lab_id=row.lab_id, restriction=row, reason=reason, proposed_by=proposer, proposed_at=now
    )
    RestrictionEndProposal.objects.filter(pk=proposal.pk).update(
        confirmed_by=confirmer, confirmed_at=now
    )
    StrainRestriction.objects.filter(pk=row.pk).update(ended_at=now, end_reason=reason)


def raw_strain(lab: Lab, taxon: Taxon, **fields: Any) -> Strain:
    values: dict[str, Any] = {
        "lab": lab,
        "accession_number": "MYC 900",
        "accession_seq": 900,
        "status": StrainStatus.ACTIVE,
        "name_as_received": "raw",
        "taxon": taxon,
        "risk_group": 1,
        "animal_pathogenicity": "unknown",
        "plant_pathogenicity": "unknown",
        **fields,
    }
    return Strain.objects.create(**values)


def test_accession_numbers_are_unique_per_lab_ignoring_case(
    lab: Lab, other_lab: Lab, exempli: Taxon
) -> None:
    raw_strain(lab, exempli, accession_number="MYC 1234a", accession_seq=None)
    with refused("strains_strain_accession_number_uniq"), transaction.atomic():
        raw_strain(lab, exempli, accession_number="myc 1234A", accession_seq=None)
    raw_strain(other_lab, exempli, accession_number="MYC 1234a", accession_seq=None)  # another lab


def test_sequences_are_unique_per_lab(lab: Lab, other_lab: Lab, exempli: Taxon) -> None:
    raw_strain(lab, exempli, accession_number="MYC 7", accession_seq=7)
    with refused("strains_strain_lab_accession_seq_uniq"), transaction.atomic():
        raw_strain(lab, exempli, accession_number="MYC 7b", accession_seq=7)
    raw_strain(other_lab, exempli, accession_number="BAC 7", accession_seq=7)


def test_legacy_and_pending_strains_have_no_sequence_and_do_not_collide(
    lab: Lab, exempli: Taxon
) -> None:
    raw_strain(lab, exempli, accession_number="MYC 12a", accession_seq=None)
    raw_strain(lab, exempli, accession_number="MYC 12b", accession_seq=None)
    raw_strain(lab, exempli, accession_number=None, accession_seq=None, status=StrainStatus.PENDING)
    raw_strain(lab, exempli, accession_number=None, accession_seq=None, status=StrainStatus.PENDING)
    assert Strain.objects.filter(accession_seq__isnull=True).count() == 4


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"accession_seq": 0}, "strains_strain_accession_seq_positive"),
        ({"accession_number": " MYC 1"}, "strains_strain_accession_number_trimmed"),
        ({"accession_number": ""}, "strains_strain_accession_number_trimmed"),
        (
            {"status": StrainStatus.PENDING, "accession_number": None, "accession_seq": 5},
            "strains_strain_seq_has_number",
        ),
        (
            {"status": StrainStatus.ACTIVE, "accession_number": None, "accession_seq": None},
            "strains_strain_numbered_unless_pending",
        ),
        ({"status": StrainStatus.PENDING}, "strains_strain_numbered_unless_pending"),
        ({"status": "lost"}, "strains_strain_numbered_unless_pending"),
        ({"name_as_received": ""}, "strains_strain_name_as_received_trimmed"),
        ({"name_as_received": "T. exempli "}, "strains_strain_name_as_received_trimmed"),
        ({"risk_group": 0}, "strains_strain_risk_group_1_to_4"),
        ({"risk_group": 5}, "strains_strain_risk_group_1_to_4"),
        ({"animal_pathogenicity": "harmless"}, "strains_strain_pathogenicity_valid"),
        ({"plant_pathogenicity": ""}, "strains_strain_pathogenicity_valid"),
        ({"country_of_origin": "XK"}, "strains_strain_country_iso_3166"),
        ({"country_of_origin": "cz"}, "strains_strain_country_iso_3166"),
        ({"isolation_date": "2026-13"}, "strains_strain_isolation_date_iso_8601"),
        ({"isolation_date": "26-01-01"}, "strains_strain_isolation_date_iso_8601"),
        ({"isolation_date": "2026-1-1"}, "strains_strain_isolation_date_iso_8601"),
        ({"isolation_source": " soil"}, "strains_strain_isolation_source_trimmed"),
    ],
)
def test_a_strain_row_that_cannot_be_true_is_refused(
    lab: Lab, exempli: Taxon, fields: dict[str, Any], constraint: str
) -> None:
    with refused(constraint), transaction.atomic():
        raw_strain(lab, exempli, **fields)


@pytest.mark.parametrize("risk_group", [1, 2, 3, 4])
def test_risk_groups_one_to_four_are_stored(lab: Lab, exempli: Taxon, risk_group: int) -> None:
    """4 is a valid fact for the database; the services refuse it at accession (ADR 0009)."""
    assert raw_strain(lab, exempli, risk_group=risk_group).risk_group == risk_group


@pytest.mark.parametrize("value", ["", "2019", "2019-05", "2019-05-31", "CZ"])
def test_origin_values_that_are_allowed(lab: Lab, exempli: Taxon, value: str) -> None:
    field = "country_of_origin" if value == "CZ" else "isolation_date"
    raw_strain(lab, exempli, **{field: value})


def test_one_current_identification_per_strain(make_strain: MakeStrain, mockia: Taxon) -> None:
    strain = make_strain()
    with refused("strains_identification_one_current"), transaction.atomic():
        StrainIdentification.objects.create(
            lab=strain.lab,
            strain=strain,
            taxon=mockia,
            identified_on=date(2026, 2, 1),
            method="m",
            reason="r",
            is_current=True,
        )
    StrainIdentification.objects.create(
        lab=strain.lab,
        strain=strain,
        taxon=mockia,
        identified_on=date(2026, 2, 1),
        method="m",
        reason="r",
        is_current=False,
    )


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"method": ""}, "strains_identification_method_trimmed"),
        ({"reason": " "}, "strains_identification_reason_given"),
    ],
)
def test_an_identification_says_how_and_why(
    make_strain: MakeStrain, mockia: Taxon, fields: dict[str, Any], constraint: str
) -> None:
    strain = make_strain()
    values: dict[str, Any] = {"method": "m", "reason": "r", **fields}
    with refused(constraint), transaction.atomic():
        StrainIdentification.objects.create(
            lab=strain.lab,
            strain=strain,
            taxon=mockia,
            identified_on=date(2026, 2, 1),
            is_current=False,
            **values,
        )


def restriction(strain: Strain, **fields: Any) -> StrainRestriction:
    values: dict[str, Any] = {
        "kind": RestrictionKind.CZ_RAT,
        "reference": "Příloha 2, bod 1",
        **fields,
    }
    return StrainRestriction.objects.create(lab=strain.lab, strain=strain, **values)


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"kind": "toxin"}, "strains_restriction_kind_valid"),
        ({"reference": ""}, "strains_restriction_reference_trimmed"),
        (
            {"kind": "dual_use", "reference": "1C350", "act": "(EU) 2025/2003"},
            "strains_restriction_dual_use_entry",
        ),
        (
            {"kind": "dual_use", "reference": "1C351.f", "act": "(EU) 2025/2003"},
            "strains_restriction_dual_use_entry",
        ),
        (
            {"kind": "dual_use", "reference": "1C351.c", "act": ""},
            "strains_restriction_act_iff_dual_use",
        ),
        (
            {"kind": "dual_use", "reference": "1C351.c", "act": "2025/2003"},
            "strains_restriction_act_iff_dual_use",
        ),
        ({"act": "(EU) 2025/2003"}, "strains_restriction_act_iff_dual_use"),
        ({"kind": "gmo", "gmo_category": None}, "strains_restriction_category_iff_gmo"),
        ({"kind": "gmo", "gmo_category": 5}, "strains_restriction_category_iff_gmo"),
        ({"gmo_category": 1}, "strains_restriction_category_iff_gmo"),
        ({"ended_at": Now(), "end_reason": ""}, "strains_restriction_end_has_reason"),
        ({"end_reason": "annex changed"}, "strains_restriction_end_has_reason"),
    ],
)
def test_a_restriction_has_the_fields_of_its_kind(
    make_strain: MakeStrain, fields: dict[str, Any], constraint: str
) -> None:
    strain = make_strain()
    with refused(constraint), transaction.atomic():
        restriction(strain, **fields)


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "dual_use", "reference": "1C351", "act": "(EU) 2025/2003"},
        {"kind": "dual_use", "reference": "1C351.a.12", "act": "(EU) 2025/2003"},
        {"kind": "dual_use", "reference": "1C354.c", "act": "(EU) 2025/2003"},
        {"kind": "gmo", "reference": "notification 1", "gmo_category": 4},
    ],
)
def test_restrictions_of_the_right_shape_are_stored(
    make_strain: MakeStrain, fields: dict[str, Any]
) -> None:
    restriction(make_strain(), **fields)


def test_one_active_restriction_of_a_kind_and_entry_per_strain(
    make_strain: MakeStrain, curator: User, manager: User
) -> None:
    strain = make_strain()
    first = restriction(strain)
    with refused("strains_restriction_active_uniq"), transaction.atomic():
        restriction(strain)
    raw_end(first, curator, manager, "annex changed")
    restriction(strain)  # once ended, the same entry may come back


def test_the_counter_never_goes_below_zero(lab: Lab) -> None:
    with (
        refused("strains_counter_seq_not_negative|out of range|violates check"),
        transaction.atomic(),
    ):
        StrainCounter.objects.create(lab=lab, last_seq=-1)


# The guards (migration 0003): what no writer may change, the owner included.


def test_a_strain_is_never_deleted(lab: Lab, exempli: Taxon) -> None:
    """Raw SQL on a strain nothing points at: Django's PROTECT never gets a say."""
    strain = raw_strain(lab, exempli)
    with guarded("strains are never deleted"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM strains_strain WHERE id = %s", [strain.pk])
    assert Strain.objects.filter(pk=strain.pk).exists()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name_as_received": "renamed"}, "the name as received never changes"),
        ({"accession_number": "MYC 99"}, "an accession number never changes"),
        ({"accession_seq": 99}, "an accession number never changes"),
        ({"lab": None}, "a strain stays in its lab"),
        ({"public_id": "00000000-0000-4000-8000-000000000001"}, "a strain keeps its public id"),
    ],
)
def test_identity_never_changes(
    make_strain: MakeStrain, other_lab: Lab, change: dict[str, Any], message: str
) -> None:
    strain = make_strain()
    values = {**change, "lab": other_lab} if "lab" in change else change
    with guarded(message), transaction.atomic():
        Strain.objects.filter(pk=strain.pk).update(**values)
    strain.refresh_from_db()
    assert (strain.accession_number, strain.name_as_received) == ("MYC 1", "Testella exempli T1")


def test_a_pending_strain_gets_its_number_once(lab: Lab, exempli: Taxon) -> None:
    pending = raw_strain(
        lab, exempli, accession_number=None, accession_seq=None, status=StrainStatus.PENDING
    )
    Strain.objects.filter(pk=pending.pk).update(
        accession_number="MYC 3", accession_seq=3, status=StrainStatus.ACTIVE
    )
    with guarded("an accession number never changes"), transaction.atomic():
        Strain.objects.filter(pk=pending.pk).update(accession_number="MYC 4", accession_seq=4)


def test_other_strain_fields_may_change(make_strain: MakeStrain) -> None:
    strain = make_strain()
    Strain.objects.filter(pk=strain.pk).update(risk_group=2, isolation_source="soil")
    strain.refresh_from_db()
    assert (strain.risk_group, strain.isolation_source) == (2, "soil")


def test_an_identification_only_stops_being_current(make_strain: MakeStrain, mockia: Taxon) -> None:
    current = StrainIdentification.objects.get(strain=make_strain())
    for change in (
        {"taxon": mockia},
        {"method": "other"},
        {"reason": "other"},
        {"identified_on": date(2020, 1, 1)},
    ):
        with guarded("an identification only stops being current"), transaction.atomic():
            StrainIdentification.objects.filter(pk=current.pk).update(**change)
    StrainIdentification.objects.filter(pk=current.pk).update(is_current=False)
    with guarded("an identification only stops being current"), transaction.atomic():
        StrainIdentification.objects.filter(pk=current.pk).update(is_current=True)
    with guarded("identifications are history and never deleted"), transaction.atomic():
        StrainIdentification.objects.filter(pk=current.pk).delete()


def test_a_restriction_only_ends_once(
    make_strain: MakeStrain, curator: User, manager: User
) -> None:
    row = restriction(make_strain())
    with guarded("a restriction only ends, once"), transaction.atomic():
        StrainRestriction.objects.filter(pk=row.pk).update(reference="Příloha 2, bod 9")
    raw_end(row, curator, manager, "annex changed")
    for change in ({"end_reason": "other"}, {"ended_at": None, "end_reason": ""}):
        with guarded("a restriction only ends, once"), transaction.atomic():
            StrainRestriction.objects.filter(pk=row.pk).update(**change)
    # Raw SQL: its proposal is a PROTECT reference, and Django would refuse before the guard.
    with (
        guarded("restrictions are history and never deleted"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM strains_strainrestriction WHERE id = %s", [row.pk])

"""Every public service of cultures.strains and cultures.biosafety takes the lab lock first.

Each one has a scenario here, run with the SQL captured, or a reviewed exemption. The
captured SQL must show the lab row locked (SELECT ... FROM "labs_lab" ... FOR UPDATE)
before the service reads the actor's role (labs_membership), the lab's permits
(biosafety_labauthorisation) or the counter (strains_straincounter), and before its
first write to a strains or biosafety table. A new service fails until someone puts it on
one side. SQL is text: the thread race in test_concurrency.py proves what PostgreSQL does.
"""

from collections.abc import Callable
from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cultures.audit.context import AuditContext
from cultures.biosafety import services as biosafety
from cultures.biosafety.models import AuthorisationKind
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab
from cultures.labs.tests.test_lock_invariant import first, locks, public_services
from cultures.strains import services as strains
from cultures.strains.models import StrainRestriction
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .conftest import DUAL_USE, GMO, MakeStrain, make_permit, new_strain

pytestmark = pytest.mark.django_db

Fixtures = tuple[Lab, Access, Taxon, MakeStrain]
Scenario = Callable[[Fixtures], Callable[[], object]]


def strain_create(f: Fixtures) -> Callable[[], object]:
    lab, access, taxon, _ = f
    return lambda: strains.strain_create(
        access=access, lab=lab, data=new_strain(taxon, restrictions=[DUAL_USE])
    )


def strain_reclassify(f: Fixtures) -> Callable[[], object]:
    _, access, taxon, make = f
    strain = make()
    return lambda: strains.strain_reclassify(
        access=access,
        strain=strain,
        taxon=taxon,
        identified_on=date(2026, 2, 1),
        method="m",
        reason="r",
    )


def strain_set_risk_group(f: Fixtures) -> Callable[[], object]:
    _, access, _, make = f
    strain = make()
    return lambda: strains.strain_set_risk_group(
        access=access, strain=strain, risk_group=2, reason="r"
    )


def strain_restriction_add(f: Fixtures) -> Callable[[], object]:
    _, access, _, make = f
    strain = make()
    return lambda: strains.strain_restriction_add(
        access=access, strain=strain, restriction=GMO, reason="r"
    )


def strain_restriction_end(f: Fixtures) -> Callable[[], object]:
    _, access, _, make = f
    restriction = StrainRestriction.objects.get(strain=make(restrictions=[GMO]))
    return lambda: strains.strain_restriction_end(
        access=access, restriction=restriction, reason="r"
    )


def authorisation_create(f: Fixtures) -> Callable[[], object]:
    lab = f[0]
    return lambda: biosafety.authorisation_create(
        lab=lab,
        kind=AuthorisationKind.CZ_VRAT,
        permit_reference="P/1",
        valid_from=date(2026, 1, 1),
        expires_on=None,
    )


def authorisation_end(f: Fixtures) -> Callable[[], object]:
    permit = make_permit(f[0], AuthorisationKind.CZ_VRAT)
    return lambda: biosafety.authorisation_end(
        authorisation=permit, ended_on=date(2026, 5, 1), reason="r"
    )


SCENARIOS: dict[str, Scenario] = {
    s.__name__: s
    for s in (
        strain_create,
        strain_reclassify,
        strain_set_risk_group,
        strain_restriction_add,
        strain_restriction_end,
        authorisation_create,
        authorisation_end,
    )
}

EXEMPT: dict[str, str] = {
    "check_partial_date": "a check on the input alone, no query",
    "check_restriction": "a check on the input alone, no query",
    "normalised": "text normalisation, no query",
}


def test_every_public_service_has_a_scenario_or_a_reviewed_exemption() -> None:
    found = public_services(strains) | public_services(biosafety)
    assert len(found) >= len(SCENARIOS)  # the walk found the services
    assert sorted(found - set(SCENARIOS) - set(EXEMPT)) == []
    assert sorted((set(SCENARIOS) | set(EXEMPT)) - found) == []


def reads(table: str) -> Callable[[str], bool]:
    return lambda sql: sql.startswith("SELECT") and f'FROM "{table}"' in sql


def writes(sql: str) -> bool:
    return sql.startswith(("INSERT INTO", "UPDATE")) and (
        '"strains_' in sql.split("(", maxsplit=1)[0]
        or '"biosafety_' in sql.split("(", maxsplit=1)[0]
    )


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_lab_lock_comes_first(
    *,
    name: str,
    lab: Lab,
    curator: User,
    exempli: Taxon,
    make_strain: MakeStrain,
    as_curator: AuditContext,
) -> None:
    # The access object is built before the capture: the request does that before the service.
    call = SCENARIOS[name]((lab, access_for(curator), exempli, make_strain))
    with CaptureQueriesContext(connection) as captured:
        call()
    statements = [q["sql"] for q in captured.captured_queries]
    lock = first(statements, locks("labs_lab"))
    assert lock is not None, f"{name} never locks the lab:\n" + "\n".join(statements)
    for match in (
        reads("labs_membership"),
        reads("biosafety_labauthorisation"),
        reads("strains_straincounter"),
        writes,
    ):
        found = first(statements, match)
        assert found is None or found > lock, (
            f"{name}: statement {found} before the lab lock {lock}"
        )
    assert first(statements, writes) is not None, f"{name} writes nothing"


def test_the_counter_row_is_locked_too(
    lab: Lab, curator: User, exempli: Taxon, as_curator: AuditContext
) -> None:
    """Defence in depth: a later writer that skips the lab lock (an import) still waits on the
    counter row, so it never reads a number another transaction is about to hand out."""
    call = strain_create((lab, access_for(curator), exempli, lambda **_: None))  # type: ignore[arg-type]
    call()  # the counter row exists from here on
    with CaptureQueriesContext(connection) as captured:
        call()
    counter = [
        q["sql"] for q in captured.captured_queries if reads("strains_straincounter")(q["sql"])
    ]
    assert counter, "the second accession reads the counter"
    assert all(sql.rstrip().endswith("FOR UPDATE") for sql in counter), counter

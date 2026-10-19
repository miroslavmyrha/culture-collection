"""Every public service of cultures.deposits takes the lab lock first.

Each one has a scenario here, run with the SQL captured, or a reviewed exemption. The
captured SQL must show the lab row locked (SELECT ... FROM "labs_lab" ... FOR UPDATE)
before the service reads the actor's role (labs_membership), a deposit row, the lab's
permits or the strain counter, and before its first write to a deposits, lineage or
strains table. A new service fails until someone puts it on one side. SQL is text: the
thread race in test_concurrency.py proves what PostgreSQL does.
"""

from collections.abc import Callable

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cultures.audit.context import AuditContext
from cultures.biosafety.policy import permit_today
from cultures.deposits import services
from cultures.deposits.models import Condition, Depositor
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.tests.test_lock_invariant import first, locks, public_services
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import GMO, JANA, MakeDeposit, facts, terms

pytestmark = pytest.mark.django_db

Fixtures = tuple[Lab, User, User, Taxon, Depositor, MakeDeposit]
Scenario = Callable[[Fixtures], Callable[[], object]]


def depositor_create(f: Fixtures) -> Callable[[], object]:
    lab, curator, *_ = f
    access = access_for(curator)  # the request builds it first
    return lambda: services.depositor_create(access=access, lab=lab, contact=JANA)


def depositor_update(f: Fixtures) -> Callable[[], object]:
    _, curator, _, _, depositor, _ = f
    access = access_for(curator)  # the request builds it first
    return lambda: services.depositor_update(
        access=access, depositor=depositor, contact=JANA, institution="Changed"
    )


def contact_erase(f: Fixtures) -> Callable[[], object]:
    depositor = f[4]
    return lambda: services.contact_erase(contact=depositor.contact, reason="erasure request")


def mta_template_publish(f: Fixtures) -> Callable[[], object]:
    lab, _, manager, *_ = f
    access = access_for(manager)  # the request builds it first
    return lambda: services.mta_template_publish(
        access=access, lab=lab, code="STD", title="T", text="x"
    )


def deposit_receive(f: Fixtures) -> Callable[[], object]:
    lab, curator, _, _, depositor, _ = f
    access = access_for(curator)  # the request builds it first
    return lambda: services.deposit_receive(
        access=access,
        lab=lab,
        data=services.NewDeposit(
            depositor=depositor,
            received_on=permit_today(),
            condition=Condition.INTACT,
            name_as_received="n",
            terms=terms(),
        ),
    )


def deposit_terms_replace(f: Fixtures) -> Callable[[], object]:
    curator, make = f[1], f[5]
    deposit = make()
    access = access_for(curator)  # the request builds it first
    return lambda: services.deposit_terms_replace(
        access=access, deposit=deposit, terms=terms(), reason="r"
    )


def deposit_start_check(f: Fixtures) -> Callable[[], object]:
    curator, make = f[1], f[5]
    deposit = make()
    access = access_for(curator)  # the request builds it first
    return lambda: services.deposit_start_check(access=access, deposit=deposit)


def deposit_accept(f: Fixtures) -> Callable[[], object]:
    _, curator, _, taxon, _, make = f
    deposit = make("checking")
    access = access_for(curator)  # the request builds it first
    return lambda: services.deposit_accept(
        access=access, deposit=deposit, facts=facts(taxon, restrictions=[GMO])
    )


def deposit_reject(f: Fixtures) -> Callable[[], object]:
    curator, make = f[1], f[5]
    deposit = make("checking")
    access = access_for(curator)  # the request builds it first
    return lambda: services.deposit_reject(access=access, deposit=deposit, reason="r")


SCENARIOS: dict[str, Scenario] = {
    s.__name__: s
    for s in (
        depositor_create,
        depositor_update,
        contact_erase,
        mta_template_publish,
        deposit_receive,
        deposit_terms_replace,
        deposit_start_check,
        deposit_accept,
        deposit_reject,
    )
}

EXEMPT: dict[str, str] = {
    "mta_text": "text normalisation, no query",
    "sha256_of": "a hash of the input, no query",
}


def test_every_public_service_has_a_scenario_or_a_reviewed_exemption() -> None:
    found = public_services(services)
    assert len(found) >= len(SCENARIOS)  # the walk found the services
    assert sorted(found - set(SCENARIOS) - set(EXEMPT)) == []
    assert sorted((set(SCENARIOS) | set(EXEMPT)) - found) == []


def reads(table: str) -> Callable[[str], bool]:
    return lambda sql: sql.startswith("SELECT") and f'FROM "{table}"' in sql


def writes(sql: str) -> bool:
    target = sql.split("(", maxsplit=1)[0]
    return sql.startswith(("INSERT INTO", "UPDATE")) and any(
        f'"{prefix}_' in target for prefix in ("deposits", "lineage", "strains")
    )


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_lab_lock_comes_first(
    *,
    name: str,
    lab: Lab,
    curator: User,
    manager: User,
    exempli: Taxon,
    depositor: Depositor,
    make_deposit: MakeDeposit,
    as_curator: AuditContext,
) -> None:
    call = SCENARIOS[name]((lab, curator, manager, exempli, depositor, make_deposit))
    with CaptureQueriesContext(connection) as captured:
        call()
    statements = [q["sql"] for q in captured.captured_queries]
    lock = first(statements, locks("labs_lab"))
    assert lock is not None, f"{name} never locks the lab:\n" + "\n".join(statements)
    for match in (
        reads("labs_membership"),
        reads("deposits_deposit"),
        reads("deposits_contact"),
        reads("biosafety_labauthorisation"),
        reads("strains_straincounter"),
        writes,
    ):
        found = first(statements, match)
        assert found is None or found > lock, (
            f"{name}: statement {found} before the lab lock {lock}"
        )
    assert first(statements, writes) is not None, f"{name} writes nothing"

"""Every public write of cultures.distribution takes the lab lock first, then the request,
then its strains, then the batches (a shipment), then the vials: lab, request, strain, batch,
vial, box, as everywhere
(lineage keeps lab, strain, batch, vial, box; a request sits between the lab and its strains).

Each service has a scenario here, run with the SQL captured, or a reviewed exemption. The
captured SQL must show the lab row locked before the actor's role is read and before anything
of distribution, a strain or a vial is read or written. A new service fails until someone puts
it on one side. SQL is text: test_concurrency.py proves what PostgreSQL does with it.
"""

from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cultures.audit.context import AuditContext
from cultures.distribution import services
from cultures.labs.access import access_for
from cultures.labs.tests.test_lock_invariant import first, locks, public_services
from cultures.users.models import User

from .test_services import NOT_A_WRITE, SCENARIOS

pytestmark = pytest.mark.django_db

EXEMPT = dict.fromkeys(NOT_A_WRITE, "no query: input checks and text") | {
    "requests_cancel_for_deaccession_locked": (
        "the deaccession's step (#20), called under its lab and strain locks"
        " (strains/tests/test_lock_invariant.py)"
    ),
}
# The services that decide on a request: they lock it before its strains and vials.
DECISIONS = {
    "request_approve",
    "request_reject",
    "request_cancel",
    "acceptance_record",
    "depositor_answer_record",
    "request_ship",
    "request_prepare_shipment",
    "request_confirm_shipment",
    "request_withdraw_shipment",
}
# The services that change vials: they lock them after the strains.
RESERVING = {"request_approve", "request_cancel", "request_ship", "request_confirm_shipment"}
# The services that may move a batch: they lock it after the strains and before its vials.
BATCHES = {"request_ship", "request_confirm_shipment"}


def test_every_public_service_has_a_scenario_or_a_reviewed_exemption() -> None:
    found = public_services(services)
    assert len(found) >= len(SCENARIOS)
    assert sorted(found - set(SCENARIOS) - set(EXEMPT)) == []
    assert sorted((set(SCENARIOS) | set(EXEMPT)) - found) == []


def reads(table: str) -> Callable[[str], bool]:
    return lambda sql: sql.startswith("SELECT") and f'FROM "{table}"' in sql


def writes(sql: str) -> bool:
    return sql.startswith(("INSERT INTO", "UPDATE")) and (
        '"distribution_' in sql.split("(", 1)[0] or '"lineage_vial"' in sql.split("(", 1)[0]
    )


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_lab_lock_comes_first_then_request_strain_vial(
    *, name: str, as_curator: AuditContext, curator: User, world: dict[str, Any]
) -> None:
    access = access_for(curator)  # the request builds it before the service runs
    with CaptureQueriesContext(connection) as captured:
        SCENARIOS[name](access, world)
    statements = [q["sql"] for q in captured.captured_queries]
    lock = first(statements, locks("labs_lab"))
    assert lock is not None, f"{name} never locks the lab:\n" + "\n".join(statements)
    for match in (
        reads("labs_membership"),
        reads("distribution_distributionrequest"),
        reads("distribution_requester"),
        reads("distribution_recipientpermit"),
        reads("distribution_vialreservation"),
        reads("distribution_shipmentpreparation"),
        reads("strains_strain"),
        reads("lineage_vial"),
        writes,
    ):
        found = first(statements, match)
        assert found is None or found > lock, f"{name}: statement {found} before the lab lock"
    request_lock = first(statements, locks("distribution_distributionrequest"))
    strain_lock = first(statements, locks("strains_strain"))
    vial_lock = first(statements, locks("lineage_vial"))
    if name in DECISIONS:
        assert request_lock is not None, f"{name} decides on a request it never locked"
    if request_lock is not None and strain_lock is not None:
        assert request_lock < strain_lock, f"{name} locks a strain before the request"
    if name in RESERVING:
        assert strain_lock is not None and vial_lock is not None, name
        assert strain_lock < vial_lock, f"{name} locks a vial before its strain"
    batch_lock = first(statements, locks("lineage_batch"))
    if name in BATCHES:
        assert batch_lock is not None, f"{name} moves batches it never locked"
        assert strain_lock is not None and vial_lock is not None, name
        assert strain_lock < batch_lock < vial_lock, f"{name}: lock order strain, batch, vial"
    else:
        assert batch_lock is None, f"{name} locks a batch: add it to BATCHES"

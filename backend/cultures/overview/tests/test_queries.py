"""Exact, flat query counts of Home's reads (#69): one row of every kind and twenty cost the same,
and the lab scope is in the SQL (a count cannot see a lost scope)."""

from collections.abc import Callable
from datetime import timedelta

import pytest

from cultures.biosafety.models import AuthorisationKind
from cultures.biosafety.policy import permit_today
from cultures.core.testing import QueryBaseline, logged_in
from cultures.deposits.tests.support import MakeDeposit
from cultures.distribution.models import PermitKind, Requester
from cultures.distribution.tests.support import Supply, add_permit, as_actor, submit
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.lineage import services as lineage
from cultures.lineage.models import Batch, VialStatus
from cultures.lineage.tests.support import vials_of
from cultures.strains.tests.conftest import make_permit
from cultures.users.models import User

from .support import ACTIVITY_URL, OVERVIEW_URL

pytestmark = pytest.mark.django_db


def scoped(queries: list[dict[str, str]], table: str) -> list[str]:
    return [q["sql"] for q in queries if f'"{table}"."lab_id" IN (' in q["sql"]]


@pytest.fixture
def every_kind(
    *, make_deposit: MakeDeposit, supply: Supply, lab: Lab, requester: Requester, curator: User
) -> Callable[[int], None]:
    """`rows` of each kind a manager sees on Home, and the lab's figures."""

    def make(rows: int) -> None:
        today = permit_today()
        for i in range(rows):
            make_deposit(name_as_received=f"Testella exempli Q{i}")
            strain = supply(release=False, vials=2)
            vial = vials_of(Batch.objects.get(strain=strain))[0]
            with as_actor(curator):
                lineage.vial_transition(
                    access=access_for(curator),
                    vial=vial,
                    status=VialStatus.TO_DESTROY,
                    reason="Cracked.",
                )
            submit(curator, lab, requester, [(strain, 1)])
            add_permit(
                curator,
                requester,
                PermitKind.SUJB_RAT_NOTICE,
                reference=f"DEV/RAT/{i}",
                valid_from=today - timedelta(days=9),
                expires_on=today + timedelta(days=9),
            )
            make_permit(
                lab,
                AuthorisationKind.CZ_VRAT,
                permit_reference=f"DEV/VRAT/{i}",
                expires_on=today + timedelta(days=9),
            )

    return make


@pytest.mark.parametrize("rows", [1, 20])  # one key for both sizes: the count must not grow
def test_the_overview_query_count_is_exact_and_flat(
    rows: int, every_kind: Callable[[int], None], manager: User, query_baseline: QueryBaseline
) -> None:
    every_kind(rows)
    client = logged_in(manager)
    # Session, user, memberships; labs, strains, batches, vials, free positions, requests and
    # deposits counted per lab; then deposits, batches, requests, recipient permits, lab
    # permits and vials to destroy, each one query for all its rows.
    with query_baseline("overview_manager") as captured:
        response = client.get(OVERVIEW_URL)
    kinds = {group["kind"]: group["total"] for group in response.json()["waiting"]}
    assert kinds == {
        "deposit_received": rows,
        "batch_checks_missing": rows,
        "request_to_decide": rows,
        "recipient_permit_expiring": rows,
        "lab_permit_expiring": rows,
        "vials_to_destroy": rows,
    }
    for table in (
        "deposits_deposit",
        "lineage_batch",
        "distribution_distributionrequest",
        "lineage_vial",
    ):
        assert scoped(captured.captured_queries, table), table


@pytest.mark.parametrize("rows", [1, 20])
def test_the_activity_query_count_is_exact_and_flat(
    rows: int, every_kind: Callable[[int], None], viewer: User, query_baseline: QueryBaseline
) -> None:
    every_kind(rows)
    client = logged_in(viewer)
    # Session, user, memberships, and the events with every label in one query.
    with query_baseline("activity") as captured:
        response = client.get(ACTIVITY_URL)
    assert 0 < len(response.json()["results"]) <= 20
    assert scoped(captured.captured_queries, "audit_auditevent")

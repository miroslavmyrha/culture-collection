"""The strain list's count of vials that may go out and its filter (#13). The definition is the
batch figure's (selectors.distributable): an available vial of a released batch of distribution
stock of a strain that still supplies. A vial in another status, in a batch pending its checks,
on hold or of seed stock, or of a deaccessioned strain, is not counted. A count is no location,
so every role that sees the list sees it, regulated strains too."""

from typing import Any

import pytest
from django.db import connection

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import Channel
from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.labs.access import access_for
from cultures.lineage import services
from cultures.lineage.models import Passage, Purpose, Vial, VialStatus
from cultures.strains.models import Strain
from cultures.strains.tests.conftest import STRAINS_URL
from cultures.users.models import User

from .support import MakeBatch, deaccessioned_past_the_service, released, vials_of

pytestmark = pytest.mark.django_db


def counts(user: User, **params: Any) -> dict[str, int]:
    """The accession number of each listed strain and its count of vials that may go out."""
    rows = logged_in(user).get(STRAINS_URL, params).json()["results"]
    return {row["accession_number"]: row["vials_distributable"] for row in rows}


def move(vial: Vial, status: VialStatus) -> None:
    """One edge of D7 past the service (it leaves reserved to distribution), the vial trigger
    still checks it."""
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE lineage_vial SET status = %s, status_changed_at = now() WHERE id = %s",
            [status, vial.pk],
        )


@pytest.mark.usefixtures("vial_edges_alone")
def test_only_available_vials_of_a_released_batch_are_counted_per_strain(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    viewer: User,
    strain: Strain,
    regulated: Strain,
    make_batch: MakeBatch,
    passage0: Passage,
) -> None:
    first = released(technician, curator, make_batch(passage0, vial_count=4))
    second = released(technician, curator, make_batch(passage0, vial_count=3))
    vials = vials_of(first) + vials_of(second)
    # Seven vials of the strain: one each of reserved, quarantined, to_destroy, lost and
    # consumed leave two available; a vial that came back (reserved, then available) counts.
    for vial, status in zip(
        vials,
        [
            VialStatus.RESERVED,
            VialStatus.QUARANTINED,
            VialStatus.TO_DESTROY,
            VialStatus.LOST,
            VialStatus.CONSUMED,
        ],
        strict=False,
    ):
        move(vial, status)
    move(vials[5], VialStatus.RESERVED)
    move(vials[5], VialStatus.AVAILABLE)
    assert Vial.objects.filter(status=VialStatus.AVAILABLE).count() == 2
    assert counts(viewer) == {strain.accession_number: 2, regulated.accession_number: 0}


@pytest.mark.parametrize("case", ["pending_check", "on_hold", "seed", "deaccessioned"])
def test_an_available_vial_that_may_not_go_out_is_not_counted_and_does_not_pass_the_filter(
    *,
    case: str,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    viewer: User,
    strain: Strain,
    regulated: Strain,
    make_batch: MakeBatch,
    passage0: Passage,
) -> None:
    if case == "pending_check":
        batch = make_batch(passage0, vial_count=2)
    elif case == "seed":
        batch = released(
            technician, curator, make_batch(passage0, vial_count=2, purpose=Purpose.SEED)
        )
    else:
        batch = released(technician, curator, make_batch(passage0, vial_count=2))
    if case == "on_hold":
        with audit_context(channel=Channel.API, actor=curator, request_id="req-c"):
            services.batch_hold(access=access_for(curator), batch=batch, reason="a doubt")
    if case == "deaccessioned":
        # Past the service, which would mark the vials for destruction (#20): the strain's status
        # alone decides here.
        deaccessioned_past_the_service(strain, curator)
    assert {v.status for v in vials_of(batch)} == {VialStatus.AVAILABLE}
    number = strain.accession_number
    assert number is not None
    # The list leaves a deaccessioned strain out unless asked for its status.
    asked = {"status": "deaccessioned"} if case == "deaccessioned" else {}
    assert counts(viewer, **asked)[number] == 0
    assert number not in counts(viewer, distributable="true", **asked)
    assert number in counts(viewer, distributable="false", **asked)


def test_the_count_is_seen_by_every_role_for_a_regulated_strain_too(
    *,
    as_technician: AuditContext,
    regulated: Strain,
    make_batch: MakeBatch,
    technician: User,
    curator: User,
    viewer: User,
    manager: User,
) -> None:
    released(
        technician,
        curator,
        make_batch(Passage.objects.get(strain=regulated, number=0), vial_count=3),
    )
    number = regulated.accession_number
    assert number is not None
    for user in (viewer, technician, curator, manager):
        assert counts(user)[number] == 3


@pytest.mark.usefixtures("vial_edges_alone")
def test_the_filter_keeps_strains_with_a_vial_that_may_go_out(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    viewer: User,
    strain: Strain,
    regulated: Strain,
    make_batch: MakeBatch,
    passage0: Passage,
) -> None:
    (only,) = vials_of(released(technician, curator, make_batch(passage0, vial_count=1)))
    assert set(counts(viewer, distributable="true")) == {strain.accession_number}
    assert set(counts(viewer, distributable="false")) == {regulated.accession_number}
    assert set(counts(viewer)) == {strain.accession_number, regulated.accession_number}
    move(only, VialStatus.RESERVED)
    assert counts(viewer, distributable="true") == {}
    assert set(counts(viewer, distributable="false")) == {
        strain.accession_number,
        regulated.accession_number,
    }
    move(only, VialStatus.AVAILABLE)
    assert counts(viewer, distributable="true") == {strain.accession_number: 1}


def test_the_filter_combines_with_the_others_and_pages_by_the_filtered_count(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    viewer: User,
    strain: Strain,
    regulated: Strain,
    make_batch: MakeBatch,
    passage0: Passage,
) -> None:
    released(technician, curator, make_batch(passage0, vial_count=2))
    body = logged_in(viewer).get(STRAINS_URL, {"distributable": "true", "limit": "1"}).json()
    assert body["count"] == 1
    body = logged_in(viewer).get(STRAINS_URL, {"distributable": "true", "risk_group": "4"}).json()
    assert body["count"] == 0


def test_an_unknown_value_of_the_filter_is_400(viewer: User, strain: Strain) -> None:
    assert_problem(
        logged_in(viewer).get(STRAINS_URL, {"distributable": "maybe"}),
        400,
        "invalid",
        attr="distributable",
    )


@pytest.mark.parametrize("batches", [1, 20])
def test_the_list_with_vials_keeps_its_query_count_and_it_is_flat(
    *,
    batches: int,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    viewer: User,
    strain: Strain,
    make_batch: MakeBatch,
    passage0: Passage,
    query_baseline: QueryBaseline,
) -> None:
    # Session, user, memberships, the lab, count, page (the count of vials is a subquery in it),
    # the active restrictions prefetched: the same seven as without vials, whatever the number
    # of batches and vials.
    for _ in range(batches):
        released(technician, curator, make_batch(passage0, vial_count=2))
    client = logged_in(viewer)
    with query_baseline("strain_list_with_vials"):
        response = client.get(STRAINS_URL, {"distributable": "true"})
    assert response.json()["results"][0]["vials_distributable"] == 2 * batches

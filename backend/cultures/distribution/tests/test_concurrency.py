"""Reservations and request numbers under concurrency.

Two approvals of requests for the same few vials run as real transactions at once: the lab
lock makes the second wait and then see what the first reserved, so it is blocked, never given
a vial twice. A vial another transaction holds is skipped, not waited for
(select_for_update(skip_locked=True)). The injected races put a competing write right before
the service's own, past every lock, so the partial unique index and the counter's unique
constraint alone decide, and the service turns their violation into a conflict.
"""

import threading
from typing import Any

import pytest
from django.db import connection, transaction
from django.utils import timezone

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.biosafety.policy import permit_today
from cultures.core.testing import run_before
from cultures.distribution import services
from cultures.distribution.models import DistributionRequest, RequestCounter, VialReservation
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.lineage.models import Vial
from cultures.users.models import User

from .support import Supply, accept_mtas, approve, new_request, reserved, submit

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_requests(
    curator: User, lab: Lab, requester: Any, supply: Supply
) -> list[DistributionRequest]:
    strain = supply(vials=3)
    with audit_context(channel=Channel.API, actor=curator, request_id="req-setup"):
        requests = [submit(curator, lab, requester, [(strain, 2)]) for _ in range(2)]
        for request in requests:
            accept_mtas(curator, request)
    return requests


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_two_approvals_of_the_same_vials_one_wins(
    curator: User, manager: User, two_requests: list[DistributionRequest]
) -> None:
    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}

    def run(name: str, actor: User, request: DistributionRequest) -> None:
        try:
            with audit_context(channel=Channel.API, actor=actor, request_id=f"req-{name}"):
                barrier.wait(timeout=5)
                services.request_approve(access=access_for(actor), request=request)
            outcomes[name] = "approved"
        except (services.RequestBlocked, services.NotEnoughVials):
            outcomes[name] = "short"
        finally:
            connection.close()

    threads = [
        threading.Thread(target=run, args=("a", curator, two_requests[0])),
        threading.Thread(target=run, args=("b", manager, two_requests[1])),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes.values()) == ["approved", "short"]
    assert VialReservation.objects.count() == 2
    assert Vial.objects.filter(status="reserved").count() == 2
    assert AuditEvent.objects.filter(event_type="request_approved").count() == 1


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_a_vial_held_elsewhere_is_skipped_not_waited_for(
    curator: User, lab: Lab, requester: Any, supply: Supply
) -> None:
    strain = supply(vials=3)
    with audit_context(channel=Channel.API, actor=curator, request_id="req-setup"):
        request = submit(curator, lab, requester, [(strain, 2)])
        accept_mtas(curator, request)
    held = Vial.objects.filter(batch__strain=strain).order_by("pk").first()
    assert held is not None
    locked, release = threading.Event(), threading.Event()

    def hold() -> None:
        try:
            with transaction.atomic():
                list(Vial.objects.select_for_update().filter(pk=held.pk))
                locked.set()
                release.wait(timeout=20)
        finally:
            connection.close()

    holder = threading.Thread(target=hold)
    holder.start()
    assert locked.wait(timeout=10)
    try:
        approve(curator, request)
    finally:
        release.set()
        holder.join(timeout=30)
    assert held.pk not in [v.pk for v in reserved(request)]
    assert len(reserved(request)) == 2


def test_the_open_reservation_index_decides_when_a_writer_skipped_the_locks(
    as_curator: Any, curator: User, lab: Lab, requester: Any, supply: Supply
) -> None:
    strain = supply(vials=3)
    request = submit(curator, lab, requester, [(strain, 1)])
    accept_mtas(curator, request)
    rival = submit(curator, lab, requester, [(strain, 1)])
    target = Vial.objects.filter(batch__strain=strain).order_by("pk").first()
    assert target is not None

    def competitor() -> None:
        VialReservation.objects.create(
            lab_id=lab.pk,
            line=rival.lines.get(),
            vial=target,
            reserved_at=timezone.now(),
            reserved_by=curator,
        )

    events = AuditEvent.objects.count()
    with run_before(services, "_save", competitor), pytest.raises(services.ReservedMeanwhile):
        approve(curator, request)
    request.refresh_from_db()
    assert request.status == "submitted"
    assert AuditEvent.objects.count() == events


def test_a_number_taken_at_the_same_moment_is_a_conflict(
    as_curator: Any, curator: User, lab: Lab, requester: Any, supply: Supply
) -> None:
    strain = supply()
    year = permit_today().year

    def competitor() -> None:
        RequestCounter.objects.create(lab=lab, year=year, last_number=0)

    with run_before(services, "_save", competitor), pytest.raises(services.NumberTaken):
        services.request_submit(
            access=access_for(curator), lab=lab, data=new_request(requester, [(strain, 1)])
        )
    assert not DistributionRequest.objects.exists()


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_two_requests_entered_at_once_get_two_numbers(
    curator: User, manager: User, lab: Lab, requester: Any, supply: Supply
) -> None:
    strain = supply()
    barrier = threading.Barrier(2)
    numbers: list[int] = []

    def run(name: str, actor: User) -> None:
        try:
            with audit_context(channel=Channel.API, actor=actor, request_id=f"req-{name}"):
                barrier.wait(timeout=5)
                created = services.request_submit(
                    access=access_for(actor), lab=lab, data=new_request(requester, [(strain, 1)])
                )
            numbers.append(created.number)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=run, args=(n, a)) for n, a in (("a", curator), ("b", manager))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(numbers) == [1, 2]

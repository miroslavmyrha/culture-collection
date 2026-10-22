"""A request's states, edge by edge: all 25 pairs through the service's one edge check and
through the trigger, against distribution.models.REQUEST_EDGES. Neither may allow a pair the
other refuses. A request moves to shipped only with its shipment, which the helper inserts
first wherever the trigger could let the move pass."""

from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction
from django.utils import timezone

from cultures.audit.context import AuditContext
from cultures.deposits.models import Contact
from cultures.distribution import services
from cultures.distribution.models import (
    REQUEST_EDGES,
    ClassificationBasis,
    DistributionRequest,
    PackingInstruction,
    RequestStatus,
    Shipment,
    TransportClass,
)
from cultures.labs.models import Lab
from cultures.users.models import User

from .support import Supply, submit

pytestmark = pytest.mark.django_db
STATES = sorted(RequestStatus)
# The facts each status carries (distribution_request_facts_of_status), set with it.
FACTS = {
    "submitted": "decided_by_id = NULL, decided_at = NULL, decision_reason = '',"
    " cancelled_by_id = NULL, cancelled_at = NULL, cancel_reason = ''",
    "approved": "decided_by_id = submitted_by_id, decided_at = now()",
    "rejected": "decided_by_id = submitted_by_id, decided_at = now(), decision_reason = 'r'",
    "cancelled": "cancelled_by_id = submitted_by_id, cancelled_at = now(), cancel_reason = 'r'",
    # The approval's facts stay as they were given.
    "shipped": "decided_by_id = decided_by_id",
}
PATHS: dict[str, list[str]] = {
    "submitted": [],
    "approved": ["approved"],
    "rejected": ["rejected"],
    "cancelled": ["cancelled"],
    "shipped": ["approved", "shipped"],
}


def test_every_state_has_a_path() -> None:
    assert sorted(PATHS) == sorted(RequestStatus.values) == sorted(FACTS)
    assert sorted(REQUEST_EDGES) == STATES


def with_shipment(request: DistributionRequest) -> None:
    """The row a shipped request needs; its guard takes it only for an approved request."""
    contact = Contact.objects.create(lab=request.lab, name="Jan Odpovědný", phone="+420 555 000")
    Shipment.objects.create(
        lab=request.lab,
        request=request,
        transport_class=TransportClass.NOT_SUBJECT,
        classification_basis=ClassificationBasis.EXEMPT_NON_PATHOGENIC,
        classified_by=request.submitted_by,
        classified_at=timezone.now(),
        packing_instruction=PackingInstruction.TRIPLE,
        responsible=contact,
        carrier="Example Courier",
        shipped_by=request.submitted_by,
        shipped_at=timezone.now(),
    )


def update(request: DistributionRequest, status: str) -> None:
    current = DistributionRequest.objects.get(pk=request.pk).status
    if status == "shipped" and current == "approved":
        with_shipment(request)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE distribution_distributionrequest SET status = %s, {FACTS[status]}"  # noqa: S608
            " WHERE id = %s",
            [status, request.pk],
        )


def put(request: DistributionRequest, status: str) -> DistributionRequest:
    for step in PATHS[status]:
        update(request, step)
    return DistributionRequest.objects.get(pk=request.pk)


@pytest.fixture
def requests(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Any, supply: Supply
) -> list[DistributionRequest]:
    strain = supply()
    return [submit(curator, lab, requester, [(strain, 1)]) for _ in STATES]


@pytest.mark.parametrize("old", STATES)
def test_the_trigger_allows_exactly_the_edges(
    requests: list[DistributionRequest], old: RequestStatus
) -> None:
    for made, new in zip(requests, STATES, strict=True):
        if new == old:
            continue
        request = put(made, old)
        try:
            with transaction.atomic():
                update(request, new)
            done = True
        except (IntegrityError, InternalError) as error:
            assert "cannot go from" in str(error) or "stays as it was given" in str(error), error
            done = False
        assert done == (new in REQUEST_EDGES[old]), (old, new)


@pytest.mark.parametrize("old", STATES)
def test_the_service_allows_exactly_the_edges(
    requests: list[DistributionRequest], old: RequestStatus
) -> None:
    """_move is the one edge check every decision of a service goes through."""
    for made, new in zip(requests, STATES, strict=True):
        if new == old:
            continue
        request = put(made, old)
        try:
            services._move(request, new)
            done = True
        except services.WrongState:
            done = False
        assert done == (new in REQUEST_EDGES[old]), (old, new)


def test_a_request_is_shipped_only_with_its_shipment(requests: list[DistributionRequest]) -> None:
    request = put(requests[0], "approved")
    with (
        pytest.raises(IntegrityError, match="a request is shipped with its shipment"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE distribution_distributionrequest SET status = 'shipped' WHERE id = %s",
            [request.pk],
        )


def test_a_shipment_is_only_of_an_approved_request(requests: list[DistributionRequest]) -> None:
    for status in ("submitted", "rejected", "cancelled"):
        request = put(requests[STATES.index(RequestStatus(status))], status)
        with (
            pytest.raises(IntegrityError, match="a shipment is of an approved request"),
            transaction.atomic(),
        ):
            with_shipment(request)

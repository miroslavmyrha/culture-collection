"""What a deaccession does to requests and vials (#20, ADR 0008, D8): in the strain's transaction,
in lock order lab, strain, requests, vials, its open requests are cancelled with the reason, the
reservations of its vials end as deaccessioned, its vials still held are marked to_destroy where
they are (one event each and one batch event), and its distributed vials stay as they went: the
strain's page lists where. The rules of who may and of the two people are in
strains/tests/test_deaccession.py.
"""

from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cultures.audit.context import audited_atomic
from cultures.audit.models import AuditEvent
from cultures.biosafety.models import RestrictionKind
from cultures.core.testing import QueryBaseline, logged_in
from cultures.distribution import services
from cultures.distribution.models import (
    DistributionRequest,
    Requester,
    RequestStatus,
    ReservationEnd,
    VialReservation,
)
from cultures.labs.access import access_for
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab
from cultures.labs.tests.test_lock_invariant import first, locks
from cultures.lineage import services as lineage
from cultures.lineage.models import Vial, VialStatus
from cultures.strains import services as strains
from cultures.strains.models import DeaccessionCause, FinalUse, Strain, StrainStatus
from cultures.strains.services import Deaccession, RestrictionInput
from cultures.strains.tests.conftest import STRAINS_URL
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import (
    Regulated,
    Supply,
    accept_mtas,
    approve,
    as_actor,
    reserved,
    ship,
    snapshot,
    submit,
)

pytestmark = pytest.mark.django_db

DEAD = Deaccession(DeaccessionCause.CONTAMINATED, "Mixed culture on every plate.")
QUARANTINE = RestrictionInput(RestrictionKind.QUARANTINE_PEST, "Annex II, Part B")


def leave(user: User, strain: Strain, data: Deaccession = DEAD) -> Strain:
    with as_actor(user):
        return strains.strain_deaccession(access=access_for(user), strain=strain, data=data)


def statuses(strain: Strain) -> list[str]:
    return list(
        Vial.objects.filter(batch__strain=strain).order_by("pk").values_list("status", flat=True)
    )


@pytest.fixture
def busy(
    *, curator: User, lab: Lab, requester: Requester, supply: Supply, mockia: Taxon
) -> dict[str, Any]:
    """A strain with six vials: one shipped, two reserved by an approved request that also asks
    for another strain, one quarantined, two available; and a submitted request for it."""
    strain = supply(vials=6)
    other = supply(mockia, vials=3)
    shipped = submit(curator, lab, requester, [(strain, 1)])
    accept_mtas(curator, shipped)
    approve(curator, shipped)
    ship(curator, shipped)
    approved = submit(curator, lab, requester, [(strain, 2), (other, 1)])
    accept_mtas(curator, approved)
    approve(curator, approved)
    submitted = submit(curator, lab, requester, [(strain, 1)])
    spare = Vial.objects.filter(batch__strain=strain, status=VialStatus.AVAILABLE).first()
    assert spare is not None
    with as_actor(curator):
        lineage.vial_transition(
            access=access_for(curator),
            vial=spare,
            status=VialStatus.QUARANTINED,
            reason="Odd colonies on the purity plate.",
        )
    return {
        "strain": strain,
        "other": other,
        "shipped": shipped,
        "approved": approved,
        "submitted": submitted,
        "reserved": reserved(approved),
    }


def test_the_strain_leaves_with_its_requests_cancelled_and_its_vials_marked_for_destruction(
    curator: User, busy: dict[str, Any]
) -> None:
    strain: Strain = busy["strain"]
    assert sorted(statuses(strain)) == [
        "available",
        "available",
        "distributed",
        "quarantined",
        "reserved",
        "reserved",
    ]
    start = AuditEvent.objects.order_by("-pk").values_list("pk", flat=True).first()
    leave(curator, strain)
    strain.refresh_from_db()
    assert strain.status == StrainStatus.DEACCESSIONED

    # Requests: the open ones cancelled with the reason, the shipped one as it was.
    reason = f"{strain.accession_number} was deaccessioned: {DEAD.reason}"
    for key in ("approved", "submitted"):
        request = DistributionRequest.objects.get(pk=busy[key].pk)
        assert (request.status, request.cancel_reason, request.cancelled_by) == (
            RequestStatus.CANCELLED,
            reason,
            curator,
        )
    assert DistributionRequest.objects.get(pk=busy["shipped"].pk).status == RequestStatus.SHIPPED

    # Reservations: the strain's end as deaccessioned, the other strain's as cancelled.
    ended = VialReservation.objects.filter(line__request=busy["approved"])
    assert sorted((r.vial.batch.strain_id, r.end_reason) for r in ended) == sorted(
        [
            (strain.pk, ReservationEnd.DEACCESSIONED),
            (strain.pk, ReservationEnd.DEACCESSIONED),
            (busy["other"].pk, ReservationEnd.CANCELLED),
        ]
    )
    assert not VialReservation.objects.filter(ended_at__isnull=True).exists()

    # Vials: everything held is to be destroyed, the shipped one stays distributed, and the
    # other strain's vial is available again.
    assert sorted(statuses(strain)) == ["distributed", *["to_destroy"] * 5]
    assert statuses(busy["other"]) == ["available"] * 3

    # Events: the strain's, one batch for its vials, and the requests' own.
    events = AuditEvent.objects.filter(pk__gt=start or 0)
    batch = events.get(event_type="vials_marked_for_destruction")
    marked = events.filter(event_type="vial_status_changed", batch_id=batch.batch_id)
    assert batch.changes == {"count": [None, 5]}
    assert (batch.reason, batch.strain_id) == (
        f"Strain deaccessioned: {DEAD.reason}",
        strain.public_id,
    )
    assert marked.count() == 5
    assert {e.changes["status"][1] for e in marked} == {"to_destroy"}
    left = events.get(event_type="strain_deaccessioned")
    assert left.changes["requests_cancelled"] == [
        None,
        [busy["approved"].label, busy["submitted"].label],
    ]
    assert left.changes["vials_to_destroy"] == [None, 5]
    assert events.filter(event_type="request_cancelled").count() == 2


def test_the_lock_order_is_lab_strain_requests_vials(curator: User, busy: dict[str, Any]) -> None:
    with as_actor(curator), CaptureQueriesContext(connection) as captured:
        strains.strain_deaccession(access=access_for(curator), strain=busy["strain"], data=DEAD)
    statements = [q["sql"] for q in captured.captured_queries]
    order = [
        first(statements, locks(table))
        for table in (
            "labs_lab",
            "strains_strain",
            "distribution_distributionrequest",
            "lineage_vial",
        )
    ]
    assert None not in order, order
    assert order == sorted(order), order  # type: ignore[type-var]


def test_a_shipment_waiting_for_its_second_person_stops_the_deaccession(
    curator: User, manager: User, approver: User, regulated: Regulated
) -> None:
    """The edge awaiting_confirmation > cancelled does not exist (#89): one of the two people
    withdraws the prepared shipment first. Nothing changes meanwhile."""
    request = regulated(prepared_by=approver)
    strain = request.lines.get().strain
    with as_actor(curator):
        proposal = strains.strain_deaccession_propose(
            access=access_for(curator), strain=strain, data=DEAD
        )
    before = snapshot()
    with as_actor(manager), pytest.raises(services.RequestAwaitsConfirmation) as raised:
        strains.strain_deaccession_confirm(
            access=access_for(manager), strain=strain, proposal=proposal.public_id
        )
    assert raised.value.code == "request_awaits_confirmation"
    assert request.label in str(raised.value.detail)
    assert snapshot() == before
    assert Strain.objects.get(pk=strain.pk).status != StrainStatus.DEACCESSIONED


def test_a_deaccessioned_strain_is_not_requested_again(
    curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    strain = supply(vials=2)
    leave(curator, strain)
    with pytest.raises(services.InvalidDistribution) as raised:
        submit(curator, lab, requester, [(strain, 1)])
    assert (raised.value.code, raised.value.attr) == ("strain_deaccessioned", "lines.0.strain")


def test_two_people_take_a_regulated_strain_out_with_the_same_effects(
    curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(quantity=2)  # approved by the approver, two vials reserved
    strain = request.lines.get().strain
    with as_actor(curator):
        proposal = strains.strain_deaccession_propose(
            access=access_for(curator), strain=strain, data=DEAD
        )
    # The proposal changes nothing: the request and its reservations stand.
    assert DistributionRequest.objects.get(pk=request.pk).status == RequestStatus.APPROVED
    with as_actor(manager):
        strains.strain_deaccession_confirm(
            access=access_for(manager), strain=strain, proposal=proposal.public_id
        )
    assert DistributionRequest.objects.get(pk=request.pk).status == RequestStatus.CANCELLED
    assert set(statuses(strain)) == {"to_destroy"}


def test_a_quarantine_pest_kept_for_storage_keeps_its_vials(
    curator: User, manager: User, supply: Supply, mockia: Taxon
) -> None:
    """Final use storage (Regulation (EU) 2019/829, Annex I (h)): the material stays, so its
    vials are not marked for destruction."""
    strain = supply(mockia, restrictions=[QUARANTINE], vials=3)
    kept = Deaccession(DEAD.cause, DEAD.reason, FinalUse.STORAGE)
    with as_actor(curator):
        proposal = strains.strain_deaccession_propose(
            access=access_for(curator), strain=strain, data=kept
        )
    with as_actor(manager):
        strains.strain_deaccession_confirm(
            access=access_for(manager), strain=strain, proposal=proposal.public_id
        )
    assert statuses(strain) == ["available"] * 3
    event = AuditEvent.objects.get(event_type="strain_deaccessioned")
    assert (event.changes["final_use"], event.changes["vials_released"]) == (
        [None, "storage"],
        [None, 0],
    )
    assert not AuditEvent.objects.filter(event_type="vials_marked_for_destruction").exists()


def test_kept_material_gives_its_reserved_vials_back(
    curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    """The lineage step on its own, as the deaccession calls it for a final use that keeps the
    material: the reservations ended, a reserved vial is available again."""
    strain = supply(vials=3)
    request = submit(curator, lab, requester, [(strain, 2)])
    accept_mtas(curator, request)
    approve(curator, request)
    access = access_for(curator)
    with as_actor(curator), audited_atomic():
        lock_lab(lab.pk)
        locked = Strain.objects.select_for_update().get(pk=strain.pk)
        services.requests_cancel_for_deaccession_locked(access=access, strain=locked, reason="kept")
        changed = lineage.strain_vials_leave_locked(
            access=access, strain=locked, reason="kept", destroy=False
        )
    assert len(changed) == 2
    assert statuses(strain) == ["available"] * 3


# Where the distributed vials went (the strain's page).


def test_the_strain_lists_where_its_distributed_vials_went(
    curator: User, viewer: User, busy: dict[str, Any], query_baseline: QueryBaseline
) -> None:
    strain: Strain = busy["strain"]
    leave(curator, strain)
    client = logged_in(viewer)
    with query_baseline("strain_shipments"):
        response = client.get(f"{STRAINS_URL}{strain.public_id}/shipments/")
    assert response.status_code == 200, response.content
    shipped: DistributionRequest = busy["shipped"]
    assert response.json()["results"] == [
        {
            "request": str(shipped.public_id),
            "number": shipped.label,
            "institution": shipped.requester.institution,
            "country": shipped.destination_country,
            "shipped_at": response.json()["results"][0]["shipped_at"],
            "vials": 1,
        }
    ]
    assert response.json()["results"][0]["shipped_at"] is not None
    # The other strain went nowhere.
    other = client.get(f"{STRAINS_URL}{busy['other'].public_id}/shipments/")
    assert other.json()["results"] == []

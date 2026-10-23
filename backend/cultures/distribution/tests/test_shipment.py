"""The shipment of an approved request (#88): every reserved vial leaves at once, the gates run
again on the ship day, a regulated request waits for a second person (#89), a distribution batch
left with nothing to give is exhausted, and the database holds the shipment frozen and complete
against any writer. Regulated examples are the invented Mockia vulgaris."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import time_machine
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from cultures.audit.context import AuditContext
from cultures.audit.events import Change, record_event
from cultures.audit.models import AuditEvent
from cultures.audit.registry import REQUEST_SHIPPED
from cultures.biosafety.models import RestrictionKind
from cultures.biosafety.policy import permit_today
from cultures.core.testing import logged_in
from cultures.deposits.models import Contact
from cultures.deposits.tests.support import DUAL_USE, QUARANTINE
from cultures.distribution import services
from cultures.distribution.models import (
    ClassificationBasis,
    Coolant,
    DistributionRequest,
    PackingInstruction,
    PermitKind,
    Requester,
    RequestStatus,
    ReservationEnd,
    Shipment,
    ShipmentVial,
    TransportClass,
    VialReservation,
)
from cultures.distribution.policy import evaluate
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.lineage import services as lineage
from cultures.lineage.models import (
    Batch,
    BatchStatus,
    Passage,
    Purpose,
    RemovalReason,
    Vial,
    VialPlacement,
    VialStatus,
)
from cultures.lineage.tests.support import preserve
from cultures.storage.tests.conftest import Tree
from cultures.strains.models import Strain
from cultures.strains.services import RestrictionInput
from cultures.taxonomy.models import Taxon
from cultures.users import services as users
from cultures.users.models import User
from cultures.users.tests.test_erasure_leaves_nothing import MARK, REASON, marker_hits, system

from .support import (
    REQUESTS_URL,
    Supply,
    accept_mtas,
    add_permit,
    approve,
    as_actor,
    confirm,
    prepare,
    reserved,
    ship,
    submit,
)
from .test_services import events_since, last_pk, refused

pytestmark = pytest.mark.django_db
RAT = RestrictionInput(RestrictionKind.CZ_RAT, "Příloha 2, bod 9")


@pytest.fixture
def approved(as_curator: AuditContext, curator: User, lab: Lab, requester: Requester) -> Any:
    """An approved request for `quantity` vials of the strain, by the curator or `by`."""

    def make(
        strain: Strain, quantity: int = 1, *, by: User | None = None, reason: str = ""
    ) -> DistributionRequest:
        request = submit(curator, lab, requester, [(strain, quantity)])
        accept_mtas(curator, request)
        return approve(by or curator, request, reason)

    return make


def free(strain: Strain) -> list[Vial]:
    """The vials of the strain's distribution batches still available, in pick order."""
    return list(
        Vial.objects.filter(
            batch__strain=strain,
            batch__purpose=Purpose.DISTRIBUTION,
            status=VialStatus.AVAILABLE,
        ).order_by("pk")
    )


def batch_of(strain: Strain) -> Batch:
    return Batch.objects.get(strain=strain, purpose=Purpose.DISTRIBUTION)


# The shipment.


def test_a_curator_ships_every_reserved_vial_at_once_and_each_leaves_its_box(
    *, curator: User, supply: Supply, approved: Any, tree: Tree
) -> None:
    strain = supply(vials=6)
    first = free(strain)[0]  # approval picks in pk order: this one is reserved
    with as_actor(curator):
        lineage.vial_place(access=access_for(curator), vial=first, box=tree.box, row=1, col=1)
    request = approved(strain, 2)
    vials = reserved(request)
    start = last_pk()
    ship(curator, request, tracking_number="EX 1")

    request.refresh_from_db()
    assert request.status == RequestStatus.SHIPPED
    assert request.decided_by == curator  # the approval stays as given
    shipment = Shipment.objects.get(request=request)
    assert (
        shipment.transport_class,
        shipment.classification_basis,
        shipment.packing_instruction,
        shipment.carrier,
        shipment.tracking_number,
        shipment.classified_by,
        shipment.shipped_by,
    ) == (
        TransportClass.NOT_SUBJECT,
        ClassificationBasis.EXEMPT_NON_PATHOGENIC,
        PackingInstruction.TRIPLE,
        "Example Courier (invented example)",
        "EX 1",
        curator,
        curator,
    )
    assert (shipment.responsible.name, shipment.responsible.phone) == (
        "Jan Odpovědný",
        "+420 555 000 111",
    )
    assert sorted(
        ShipmentVial.objects.filter(shipment=shipment).values_list("vial_id", flat=True)
    ) == [v.pk for v in vials]
    assert {v.status for v in Vial.objects.filter(pk__in=[v.pk for v in vials])} == {
        VialStatus.DISTRIBUTED
    }
    assert set(
        VialReservation.objects.filter(line__request=request).values_list("end_reason", "ended_by")
    ) == {(ReservationEnd.SHIPPED, curator.pk)}
    placement = VialPlacement.objects.get(vial=first)
    assert placement.removed_at is not None
    assert placement.removal_reason == RemovalReason.DISTRIBUTED
    assert batch_of(strain).status == BatchStatus.RELEASED  # vials are left

    recorded = events_since(start)
    assert [e.event_type for e in recorded] == [
        "vial_status_changed",
        "vial_status_changed",
        "request_line_shipped",
        "request_shipped",
    ]
    assert {e.strain_id for e in recorded[:3]} == {strain.public_id}
    assert recorded[0].changes["location"] == [
        {"box": str(tree.box.public_id), "row": 1, "col": 1},
        None,
    ]
    assert recorded[2].changes["vials"] == [None, [str(v.public_id) for v in vials]]
    event = recorded[3]
    assert event.strain_id is None  # a request spans strains
    assert event.changes["status"] == ["approved", "shipped"]
    assert event.changes["shipped_on"] == [None, permit_today().isoformat()]
    assert event.changes["responsible"] == "changed"
    text = str([e.changes for e in recorded])
    assert "Odpovědný" not in text and "555 000 111" not in text


def test_a_request_ships_once_and_only_once_approved(
    *, curator: User, lab: Lab, requester: Requester, supply: Supply, approved: Any
) -> None:
    strain = supply(vials=6)
    waiting = submit(curator, lab, requester, [(strain, 1)])
    refused(services.WrongState, "request_state", lambda: ship(curator, waiting))
    request = approved(strain)
    ship(curator, request)
    refused(services.WrongState, "request_state", lambda: ship(curator, request))
    refused(
        services.WrongState,
        "request_state",
        lambda: services.request_cancel(
            access=access_for(curator), request=request, reason="too late"
        ),
    )


def test_a_regulated_request_waits_for_a_second_person(
    *, manager: User, curator: User, supply: Supply, mockia: Taxon, approved: Any
) -> None:
    strain = supply(mockia, restrictions=[DUAL_USE])
    request = approved(strain, by=manager, reason="Dual-use inside the EU needs no licence.")
    for actor in (curator, manager):
        error = refused(
            services.SecondPersonRequired,
            "second_person_required",
            lambda actor=actor: ship(actor, request),  # type: ignore[misc]
        )
        assert "second person" in error.detail


# The gates again, on the ship day.


def test_a_permit_that_expired_since_the_approval_blocks_the_shipment(
    *,
    manager: User,
    curator: User,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
    approved: Any,
) -> None:
    """The ship day is today, never a day the shipper names. On the approval day the notice
    holds and the gates pass (the request then waits for the second person); a day later it
    has expired and the gates block, before any second person is asked."""
    strain = supply(mockia, restrictions=[RAT])
    today = permit_today()
    add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE, expires_on=today)
    request = approved(strain, by=manager, reason="A notified requester.")
    refused(services.SecondPersonRequired, "second_person_required", lambda: ship(curator, request))
    with time_machine.travel(timezone.now() + timedelta(days=1), tick=False):
        assert permit_today() == today + timedelta(days=1)
        error = refused(
            services.ShipmentBlocked, "shipment_blocked", lambda: ship(curator, request)
        )
    assert "notice to SÚJB" in error.detail


def test_a_batch_held_since_the_approval_blocks_until_it_is_released(
    *, curator: User, supply: Supply, approved: Any
) -> None:
    strain = supply(vials=6)
    request = approved(strain)
    batch = batch_of(strain)
    with as_actor(curator):
        lineage.batch_hold(access=access_for(curator), batch=batch, reason="Contamination seen.")
    error = refused(services.ShipmentBlocked, "shipment_blocked", lambda: ship(curator, request))
    assert "0 of its 1 reserved vials may still go out" in error.detail
    with as_actor(curator):
        lineage.batch_release(access=access_for(curator), batch=batch, reason="Checked again.")
    ship(curator, request)
    request.refresh_from_db()
    assert request.status == RequestStatus.SHIPPED


def test_a_manager_finding_is_not_asked_again_at_shipment(
    *, manager: User, curator: User, supply: Supply, approved: Any
) -> None:
    """Risk group 2 without a work permit needs a manager at approval; the shipment of the
    approved request goes ahead with a curator, as UN 3373 (a pathogen is not exempt)."""
    strain = supply(risk_group=2, vials=6)
    request = approved(strain, by=manager, reason="The destination needs no work permit.")
    refused(
        services.InvalidDistribution,
        "not_exempt",
        lambda: ship(curator, request),
        attr="classification_basis",
    )
    ship(
        curator,
        request,
        transport_class=TransportClass.UN3373,
        classification_basis=ClassificationBasis.PROFESSIONAL_JUDGEMENT,
        basis_note="A risk group 2 culture, not on the indicative list: Category B.",
        packing_instruction=PackingInstruction.P650,
        coolant=Coolant.DRY_ICE,
        coolant_kg=Decimal("2.5"),
    )
    shipment = Shipment.objects.get(request=request)
    assert (shipment.transport_class, shipment.coolant, shipment.coolant_kg) == (
        TransportClass.UN3373,
        Coolant.DRY_ICE,
        Decimal("2.50"),
    )


# The form's rules, before anything is locked.


@pytest.mark.parametrize(
    ("changes", "attr", "code"),
    [
        (
            {"classification_basis": ClassificationBasis.INDICATIVE_LIST},
            "classification_basis",
            "invalid",
        ),
        (
            {
                "transport_class": TransportClass.UN3373,
                "packing_instruction": PackingInstruction.P650,
            },
            "classification_basis",
            "invalid",
        ),
        (
            {
                "transport_class": TransportClass.UN3373,
                "classification_basis": ClassificationBasis.PROFESSIONAL_JUDGEMENT,
                "basis_note": "  ",
                "packing_instruction": PackingInstruction.P650,
            },
            "basis_note",
            "required",
        ),
        (
            {
                "transport_class": TransportClass.UN3373,
                "classification_basis": ClassificationBasis.INDICATIVE_LIST,
            },
            "packing_instruction",
            "invalid",
        ),
        ({"coolant": Coolant.DRY_ICE}, "coolant_kg", "required"),
        ({"coolant_kg": Decimal(1)}, "coolant", "invalid"),
        ({"coolant": Coolant.COLD_PACKS, "coolant_kg": Decimal(0)}, "coolant_kg", "invalid"),
        (
            {"responsible": services.ContactInput("Jan Odpovědný", phone="call the lab")},
            "responsible_phone",
            "invalid",
        ),
        (
            {"responsible": services.ContactInput(" ", phone="+420 555 000 111")},
            "responsible_name",
            "invalid",
        ),
        ({"carrier": "  "}, "carrier", "invalid"),
    ],
)
def test_shipment_errors_name_their_field_and_change_nothing(
    *, changes: dict[str, Any], attr: str, code: str, curator: User, supply: Supply, approved: Any
) -> None:
    request = approved(supply(vials=6))
    refused(services.InvalidDistribution, code, lambda: ship(curator, request, **changes), attr)


# Exhausted: a distribution batch with no vial left available or reserved.


def test_shipping_the_last_vials_exhausts_the_batch_with_a_reason(
    *, curator: User, supply: Supply, approved: Any
) -> None:
    strain = supply(vials=6)
    request = approved(strain, len(free(strain)))
    start = last_pk()
    ship(curator, request)
    batch = batch_of(strain)
    assert batch.status == BatchStatus.EXHAUSTED
    assert batch.status_reason == (
        f"No vial is left to distribute after request {request.label} was shipped."
    )
    [event] = [e for e in events_since(start) if e.event_type == "batch_status_changed"]
    assert (event.changes["status"], event.strain_id, event.reason) == (
        ["released", "exhausted"],
        strain.public_id,
        batch.status_reason,
    )


def test_a_batch_with_a_vial_left_available_stays_released(
    *, curator: User, supply: Supply, approved: Any
) -> None:
    strain = supply(vials=6)
    request = approved(strain, len(free(strain)) - 1)
    start = last_pk()
    ship(curator, request)
    assert batch_of(strain).status == BatchStatus.RELEASED
    assert "batch_status_changed" not in [e.event_type for e in events_since(start)]


def test_a_vial_reserved_for_another_request_keeps_the_batch_open(
    *, curator: User, supply: Supply, approved: Any
) -> None:
    strain = supply(vials=6)
    left = len(free(strain))
    first, second = approved(strain, left - 1), approved(strain, 1)
    ship(curator, first)
    assert batch_of(strain).status == BatchStatus.RELEASED
    ship(curator, second)
    assert batch_of(strain).status == BatchStatus.EXHAUSTED


def test_a_quarantined_or_lost_vial_does_not_keep_the_batch_open(
    *, curator: User, supply: Supply, approved: Any
) -> None:
    strain = supply(vials=6)
    quarantined, lost = free(strain)[-2:]
    with as_actor(curator):
        for vial, status in ((quarantined, VialStatus.QUARANTINED), (lost, VialStatus.LOST)):
            lineage.vial_transition(
                access=access_for(curator), vial=vial, status=status, reason="Seen on the bench."
            )
    ship(curator, approved(strain, len(free(strain))))
    assert batch_of(strain).status == BatchStatus.EXHAUSTED


def test_a_seed_batch_is_never_exhausted_by_a_shipment(*, curator: User, supply: Supply) -> None:
    """The seed stock never leaves (D15), so a shipment never empties it: the rule refuses a
    seed batch even with no vial left, whoever calls it."""
    strain = supply(vials=6)
    with as_actor(curator):
        seed = preserve(
            curator,
            Passage.objects.get(strain=strain, number=0),
            vial_count=1,
            purpose=Purpose.SEED,
        )
        for vial in Vial.objects.filter(batch=seed):
            lineage.vial_transition(
                access=access_for(curator), vial=vial, status=VialStatus.CONSUMED, reason="Revived."
            )
        locked = Batch.objects.select_related("strain").get(pk=seed.pk)
        assert lineage.batch_exhaust_if_emptied_locked(batch=locked, reason="r") is False
    assert Batch.objects.get(pk=seed.pk).status == BatchStatus.PENDING_CHECK


# The database: a shipment frozen and complete, whoever writes.


def shipment_row(request: DistributionRequest, **changes: Any) -> Shipment:
    contact = Contact.objects.create(lab=request.lab, name="Jan Odpovědný", phone="+420 555 000")
    values: dict[str, Any] = {
        "lab": request.lab,
        "request": request,
        "transport_class": TransportClass.NOT_SUBJECT,
        "classification_basis": ClassificationBasis.EXEMPT_NON_PATHOGENIC,
        "classified_by": request.submitted_by,
        "classified_at": timezone.now(),
        "packing_instruction": PackingInstruction.TRIPLE,
        "responsible": contact,
        "carrier": "Example Courier",
        "shipped_by": request.submitted_by,
        "shipped_at": timezone.now(),
        **changes,
    }
    return Shipment.objects.create(**values)


def sql(statement: str, params: list[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(statement, params)


def at_commit() -> None:
    """Runs the deferred checks now: a test's transaction never commits."""
    sql("SET CONSTRAINTS ALL IMMEDIATE", [])


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        (
            {"classification_basis": ClassificationBasis.INDICATIVE_LIST},
            "distribution_shipment_class_and_basis",
        ),
        (
            {
                "transport_class": TransportClass.UN3373,
                "classification_basis": ClassificationBasis.EXEMPT_INACTIVATED,
                "packing_instruction": PackingInstruction.P650,
            },
            "distribution_shipment_class_and_basis",
        ),
        ({"transport_class": "un2814"}, "distribution_shipment_class_and_basis"),
        (
            {
                "transport_class": TransportClass.UN3373,
                "classification_basis": ClassificationBasis.PROFESSIONAL_JUDGEMENT,
                "packing_instruction": PackingInstruction.P650,
            },
            "distribution_shipment_judgement_has_note",
        ),
        (
            {
                "transport_class": TransportClass.UN3373,
                "classification_basis": ClassificationBasis.INDICATIVE_LIST,
            },
            "distribution_shipment_un3373_in_p650",
        ),
        ({"packing_instruction": "pi620"}, "distribution_shipment_un3373_in_p650"),
        ({"coolant": Coolant.DRY_ICE}, "distribution_shipment_coolant_quantity"),
        ({"coolant_kg": Decimal(1)}, "distribution_shipment_coolant_quantity"),
        (
            {"coolant": Coolant.COLD_PACKS, "coolant_kg": Decimal(0)},
            "distribution_shipment_coolant_quantity",
        ),
        ({"coolant": "helium"}, "distribution_shipment_coolant_quantity"),
        ({"carrier": " Courier"}, "distribution_shipment_carrier_trimmed"),
        ({"tracking_number": "EX1 "}, "distribution_shipment_tracking_trimmed"),
    ],
)
def test_the_table_refuses_a_shipment_the_rules_refuse(
    *, changes: dict[str, Any], constraint: str, supply: Supply, approved: Any
) -> None:
    request = approved(supply(vials=6))
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        shipment_row(request, **changes)


def test_a_shipment_and_its_vials_never_change_or_go(
    *, curator: User, supply: Supply, approved: Any
) -> None:
    request = approved(supply(vials=6))
    ship(curator, request)
    shipment = Shipment.objects.get(request=request)
    for statement in (
        "UPDATE distribution_shipment SET carrier = 'Other' WHERE id = %s",
        "DELETE FROM distribution_shipment WHERE id = %s",
    ):
        with pytest.raises(IntegrityError, match="a shipment never changes"), transaction.atomic():
            sql(statement, [shipment.pk])
    for statement in (
        "UPDATE distribution_shipmentvial SET line_id = line_id WHERE shipment_id = %s",
        "DELETE FROM distribution_shipmentvial WHERE shipment_id = %s",
    ):
        with pytest.raises(IntegrityError, match="never change"), transaction.atomic():
            sql(statement, [shipment.pk])


def test_a_shipment_sends_only_vials_its_request_reserved(*, supply: Supply, approved: Any) -> None:
    strain = supply(vials=6)
    request, other = approved(strain), approved(strain)
    # Rolled back at the end: the shipment is left incomplete, which the check at commit refuses.
    with transaction.atomic():
        shipment = shipment_row(request)
        line = request.lines.get()
        [mine], [theirs], spare = reserved(request), reserved(other), free(strain)[0]
        for vial in (theirs, spare):
            with (
                pytest.raises(IntegrityError, match="sends a vial its request reserved"),
                transaction.atomic(),
            ):
                ShipmentVial.objects.create(shipment=shipment, line=line, vial=vial)
        ShipmentVial.objects.create(shipment=shipment, line=line, vial=mine)
        with pytest.raises(IntegrityError, match="duplicate key"), transaction.atomic():
            ShipmentVial.objects.create(shipment=shipment, line=line, vial=mine)
        transaction.set_rollback(True)


def test_a_reservation_ends_as_shipped_only_with_its_vial_in_a_shipment(
    *, supply: Supply, approved: Any
) -> None:
    request = approved(supply(vials=6))
    reservation = VialReservation.objects.get(line__request=request)
    with (
        pytest.raises(IntegrityError, match="ends as shipped with its vial in a shipment"),
        transaction.atomic(),
    ):
        sql(
            "UPDATE distribution_vialreservation SET ended_at = reserved_at,"
            " ended_by_id = reserved_by_id, end_reason = 'shipped' WHERE id = %s",
            [reservation.pk],
        )


def test_at_commit_a_vial_is_distributed_only_in_a_shipment(
    *, supply: Supply, approved: Any
) -> None:
    request = approved(supply(vials=6))
    [vial] = reserved(request)
    sql(
        "UPDATE distribution_vialreservation SET ended_at = reserved_at,"
        " ended_by_id = reserved_by_id, end_reason = 'cancelled' WHERE vial_id = %s",
        [vial.pk],
    )
    sql(
        "UPDATE lineage_vial SET status = 'distributed', status_changed_at = now() WHERE id = %s",
        [vial.pk],
    )
    with pytest.raises(IntegrityError, match="distributed only in a shipment"):
        at_commit()


def test_at_commit_a_shipment_holds_every_vial_its_request_reserved(
    *, supply: Supply, approved: Any
) -> None:
    """Two reserved vials, one shipped and one let go: the request cannot be shipped so."""
    request = approved(supply(vials=6), 2)
    shipment = shipment_row(request)
    line = request.lines.get()
    sent, kept = reserved(request)
    ShipmentVial.objects.create(shipment=shipment, line=line, vial=sent)
    for vial, end in ((sent, "shipped"), (kept, "cancelled")):
        sql(
            "UPDATE distribution_vialreservation SET ended_at = reserved_at,"
            " ended_by_id = reserved_by_id, end_reason = %s WHERE vial_id = %s",
            [end, vial.pk],
        )
    sql(
        "UPDATE lineage_vial SET status = 'distributed', status_changed_at = now() WHERE id = %s",
        [sent.pk],
    )
    sql("UPDATE lineage_vial SET status = 'available' WHERE id = %s", [kept.pk])
    sql(
        "UPDATE distribution_distributionrequest SET status = 'shipped' WHERE id = %s", [request.pk]
    )
    with pytest.raises(IntegrityError, match="sends every vial its request reserved"):
        at_commit()


def test_at_commit_a_shipment_is_of_a_shipped_request(*, supply: Supply, approved: Any) -> None:
    """Every vial sent and distributed, every reservation ended as shipped: the request must
    still say shipped."""
    request = approved(supply(vials=6))
    shipment = shipment_row(request)
    [vial] = reserved(request)
    ShipmentVial.objects.create(shipment=shipment, line=request.lines.get(), vial=vial)
    sql(
        "UPDATE distribution_vialreservation SET ended_at = reserved_at,"
        " ended_by_id = reserved_by_id, end_reason = 'shipped' WHERE vial_id = %s",
        [vial.pk],
    )
    sql(
        "UPDATE lineage_vial SET status = 'distributed', status_changed_at = now() WHERE id = %s",
        [vial.pk],
    )
    with pytest.raises(IntegrityError, match="sends every vial its request reserved"):
        at_commit()


def test_at_commit_the_reservation_of_a_shipped_vial_ended_as_shipped(
    *, supply: Supply, approved: Any
) -> None:
    """The vial sent and distributed, the request shipped, but its reservation ended as if the
    request had been cancelled."""
    request = approved(supply(vials=6))
    shipment = shipment_row(request)
    [vial] = reserved(request)
    ShipmentVial.objects.create(shipment=shipment, line=request.lines.get(), vial=vial)
    sql(
        "UPDATE distribution_vialreservation SET ended_at = reserved_at,"
        " ended_by_id = reserved_by_id, end_reason = 'cancelled' WHERE vial_id = %s",
        [vial.pk],
    )
    sql(
        "UPDATE lineage_vial SET status = 'distributed', status_changed_at = now() WHERE id = %s",
        [vial.pk],
    )
    sql(
        "UPDATE distribution_distributionrequest SET status = 'shipped' WHERE id = %s", [request.pk]
    )
    with pytest.raises(IntegrityError, match="sends every vial its request reserved"):
        at_commit()


def test_the_request_event_never_holds_the_responsible_person(
    *, as_curator: AuditContext, supply: Supply, approved: Any
) -> None:
    """Whatever a service passes: the registry masks the field (PERSONAL_FIELDS)."""
    request = approved(supply(vials=6))
    record_event(
        REQUEST_SHIPPED,
        Change(
            "distribution_request",
            request.public_id,
            {"responsible": "Jan Odpovědný"},
            lab_id=request.lab_id,
        ),
    )
    assert AuditEvent.objects.order_by("-pk").first().changes == {"responsible": "changed"}  # type: ignore[union-attr]


def test_a_shipped_request_still_counts_against_its_letter_of_authority(
    *,
    manager: User,
    curator: User,
    approver: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
    approved: Any,
) -> None:
    """A letter that allows one sending: while the first request's shipment waits for the
    second person, and once it is confirmed, a second request is blocked."""
    strain = supply(mockia, restrictions=[QUARANTINE], vials=6)
    add_permit(curator, requester, PermitKind.PLANT_HEALTH_LOA, sendings_allowed=1)
    first = approved(strain, by=manager, reason="The letter allows it.")
    second = submit(curator, lab, requester, [(strain, 1)])
    accept_mtas(curator, second)
    prepare(curator, first)
    assert {f.code for f in evaluate(second, permit_today()).blockers} == {"loa_exhausted"}
    confirm(approver, first)
    first.refresh_from_db()
    assert first.status == RequestStatus.SHIPPED
    assert {f.code for f in evaluate(second, permit_today()).blockers} == {"loa_exhausted"}


def test_a_shipment_through_the_service_passes_the_checks_at_commit(
    *, curator: User, supply: Supply, approved: Any
) -> None:
    request = approved(supply(vials=6), 2)
    ship(curator, request)
    at_commit()  # raises if a deferred check fails
    assert AuditEvent.objects.filter(event_type="request_shipped").count() == 1


def test_the_ship_day_is_a_czech_day(*, curator: User, supply: Supply, approved: Any) -> None:
    """23:30 UTC on 31 December is already 1 January in Prague."""
    request = approved(supply(vials=6))
    with time_machine.travel(datetime(2026, 12, 31, 23, 30, tzinfo=UTC), tick=False):
        start = last_pk()
        ship(curator, request)
    [event] = [e for e in events_since(start) if e.event_type == "request_shipped"]
    assert event.changes["shipped_on"] == [None, date(2027, 1, 1).isoformat()]


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_an_erased_responsible_person_leaves_no_value_in_any_column(
    *, curator: User, viewer: User, supply: Supply, approved: Any
) -> None:
    """The responsible person of a shipment is a contact (D11): shipped through the API with a
    marker in the name and a phone number of its own, then erased with erase_contact. The
    shipment row holds only the contact's id, and the events say "changed"."""
    phone = "+420 731 908 246"
    request = approved(supply(vials=6))
    response = logged_in(curator).post(
        f"{REQUESTS_URL}{request.public_id}/ship/",
        {
            "transport_class": "not_subject",
            "classification_basis": "exempt_non_pathogenic",
            "packing_instruction": "triple_packaging",
            "responsible_name": f"{MARK} Jan",
            "responsible_phone": phone,
            "carrier": "Example Courier (invented example)",
        },
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    assert marker_hits() == ["public.deposits_contact.name"]
    assert marker_hits(phone) == ["public.deposits_contact.phone"]
    with system():
        staff = users.superuser_create(username="root", password=None, reason="first admin")
    contact = Shipment.objects.get(request=request).responsible
    call_command(
        "erase_contact", str(contact.public_id), "--by", staff.username, "--reason", REASON
    )
    assert marker_hits() == marker_hits(phone) == []
    shown = logged_in(curator).get(f"{REQUESTS_URL}{request.public_id}/").json()["shipment"]
    assert (shown["responsible_name"], shown["responsible_phone"]) == ("", "")

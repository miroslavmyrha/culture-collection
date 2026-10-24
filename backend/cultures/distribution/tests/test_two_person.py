"""The shipment of a regulated request in two steps by two people (#89, ADR 0009): one person
prepares it, nothing leaves; a different person, neither the approver nor the preparer,
confirms it, the gates run again on that day, and then exactly what a shipment in one step does
happens. A preparation is withdrawn with a reason and stays. The database holds every rule
against any writer. Regulated examples are the invented Mockia vulgaris."""

from datetime import timedelta
from typing import Any

import pytest
import time_machine
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from cultures.biosafety.models import RestrictionKind
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import Forbidden, RuleViolation
from cultures.core.testing import run_before
from cultures.deposits.models import Contact
from cultures.distribution import services
from cultures.distribution.models import (
    PACKAGE_FIELDS,
    ClassificationBasis,
    DistributionRequest,
    PackingInstruction,
    PermitKind,
    Requester,
    RequestStatus,
    ReservationEnd,
    Shipment,
    ShipmentPreparation,
    TransportClass,
    VialReservation,
)
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.lineage import services as lineage
from cultures.lineage.models import Vial, VialPlacement, VialStatus
from cultures.storage.tests.conftest import Tree
from cultures.strains import services as strains
from cultures.strains.models import StrainRestriction
from cultures.strains.services import RestrictionInput
from cultures.strains.tests.conftest import end_restriction
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import (
    Regulated,
    Supply,
    accept_mtas,
    add_permit,
    approve,
    as_actor,
    confirm,
    open_preparation,
    prepare,
    reserved,
    ship,
    submit,
    withdraw,
)
from .test_services import events_since, last_pk, refused

pytestmark = pytest.mark.django_db
RAT = RestrictionInput(RestrictionKind.CZ_RAT, "Příloha 2, bod 9")


# The two steps.


def test_a_curator_prepares_and_nothing_leaves(
    *, curator: User, approver: User, regulated: Regulated
) -> None:
    request = regulated(2)
    vials = reserved(request)
    start = last_pk()
    prepare(curator, request, tracking_number="EX 9")

    request.refresh_from_db()
    assert request.status == RequestStatus.AWAITING_CONFIRMATION
    assert request.decided_by == approver  # the approval stays as given
    assert not Shipment.objects.filter(request=request).exists()
    assert reserved(request) == vials
    assert {v.status for v in Vial.objects.filter(pk__in=[v.pk for v in vials])} == {
        VialStatus.RESERVED
    }
    preparation = open_preparation(request)
    assert (preparation.prepared_by, preparation.tracking_number, preparation.withdrawn_at) == (
        curator,
        "EX 9",
        None,
    )
    assert preparation.responsible.phone == "+420 555 000 111"
    [event] = events_since(start)
    assert (event.event_type, event.actor, event.strain_id) == (
        "request_shipment_prepared",
        curator,
        None,
    )
    assert event.changes["status"] == ["approved", "awaiting_confirmation"]
    assert event.changes["preparation"] == [None, str(preparation.public_id)]
    assert event.changes["tracking_number"] == [None, "EX 9"]
    assert event.changes["responsible"] == "changed"
    assert "Odpovědný" not in str(event.changes) and "555 000 111" not in str(event.changes)


def test_a_second_person_confirms_and_the_vials_leave_with_both_people_recorded(
    *, curator: User, manager: User, regulated: Regulated, tree: Tree
) -> None:
    request = regulated(2)
    first = reserved(request)[0]
    with as_actor(curator):
        lineage.vial_place(access=access_for(curator), vial=first, box=tree.box, row=1, col=1)
    prepare(curator, request)
    preparation = open_preparation(request)
    vials = reserved(request)
    start = last_pk()
    confirm(manager, request)

    request.refresh_from_db()
    assert request.status == RequestStatus.SHIPPED
    shipment = Shipment.objects.get(request=request)
    assert shipment.preparation == preparation
    assert (shipment.classified_by, shipment.classified_at) == (
        curator,
        preparation.prepared_at,
    )
    assert shipment.shipped_by == manager
    assert {f: getattr(shipment, f) for f in PACKAGE_FIELDS} == {
        f: getattr(preparation, f) for f in PACKAGE_FIELDS
    }
    assert sorted(shipment.vials.values_list("vial_id", flat=True)) == [v.pk for v in vials]
    assert {v.status for v in Vial.objects.filter(pk__in=[v.pk for v in vials])} == {
        VialStatus.DISTRIBUTED
    }
    assert set(
        VialReservation.objects.filter(line__request=request).values_list("end_reason", "ended_by")
    ) == {(ReservationEnd.SHIPPED, manager.pk)}
    assert VialPlacement.objects.get(vial=first).removed_at is not None

    recorded = events_since(start)
    assert [e.event_type for e in recorded] == [
        "vial_status_changed",
        "vial_status_changed",
        "request_line_shipped",
        "request_shipped",
        "shipment_document_generated",
    ]
    event = recorded[-2]
    assert event.actor == manager
    assert event.changes["status"] == ["awaiting_confirmation", "shipped"]
    assert event.changes["preparation"] == [None, str(preparation.public_id)]
    assert event.changes["prepared_by"] == [None, str(curator.public_id)]
    assert event.changes["prepared_at"] == [None, preparation.prepared_at.isoformat()]
    assert event.changes["confirmed_by"] == [None, str(manager.public_id)]
    assert event.changes["confirmed_at"] == [None, shipment.shipped_at.isoformat()]
    assert event.changes["shipped_on"] == [None, permit_today().isoformat()]
    assert event.changes["responsible"] == "changed"
    assert curator.username not in str(event.changes)


def test_the_approver_may_prepare_and_another_person_confirms(
    *, approver: User, curator: User, regulated: Regulated
) -> None:
    request = regulated()
    prepare(approver, request)
    confirm(curator, request)
    request.refresh_from_db()
    assert request.status == RequestStatus.SHIPPED


# Who may confirm.


def test_the_approver_does_not_confirm(
    *, approver: User, curator: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    error = refused(
        services.ConfirmOwnApproval, "confirm_own_approval", lambda: confirm(approver, request)
    )
    assert error.status_code == 403


def test_the_preparer_does_not_confirm(*, curator: User, regulated: Regulated) -> None:
    request = regulated(prepared_by=curator)
    refused(
        services.ConfirmOwnPreparation,
        "confirm_own_preparation",
        lambda: confirm(curator, request),
    )


def test_an_approver_who_prepared_is_refused_as_the_approver(
    *, approver: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=approver)
    refused(services.ConfirmOwnApproval, "confirm_own_approval", lambda: confirm(approver, request))


def test_a_confirmation_of_another_preparation_than_the_open_one_is_a_conflict(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    """The confirmer read one preparation; it was withdrawn and prepared again meanwhile."""
    request = regulated(prepared_by=curator)
    read = open_preparation(request)
    withdraw(curator, request)
    prepare(curator, request, carrier="Another Courier (invented example)")
    refused(
        services.PreparationChanged, "preparation_changed", lambda: confirm(manager, request, read)
    )


def test_a_viewer_or_technician_neither_prepares_nor_confirms(
    *, curator: User, viewer: User, technician: User, regulated: Regulated
) -> None:
    approved = regulated()
    awaiting = regulated(prepared_by=curator)
    for actor in (viewer, technician):
        refused(Forbidden, "permission_denied", lambda a=actor: prepare(a, approved))  # type: ignore[misc]
        refused(Forbidden, "permission_denied", lambda a=actor: confirm(a, awaiting))  # type: ignore[misc]
        refused(Forbidden, "permission_denied", lambda a=actor: withdraw(a, awaiting))  # type: ignore[misc]


# Which request goes which way.


def test_a_regulated_request_is_not_shipped_in_one_step(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated()
    for actor in (curator, manager):
        error = refused(
            services.SecondPersonRequired,
            "second_person_required",
            lambda a=actor: ship(a, request),  # type: ignore[misc]
        )
        assert "prepare the shipment" in error.detail


def test_an_unregulated_request_is_not_prepared(
    *, curator: User, supply: Supply, lab: Lab, requester: Requester
) -> None:
    request = submit(curator, lab, requester, [(supply(vials=6), 1)])
    accept_mtas(curator, request)
    approve(curator, request)
    refused(services.ShipInOneStep, "ship_in_one_step", lambda: prepare(curator, request))


def test_a_request_awaiting_confirmation_is_not_shipped_in_one_step_approved_or_cancelled(
    *, curator: User, approver: User, regulated: Regulated
) -> None:
    """Even when its strain stopped being regulated meanwhile: the preparation is confirmed or
    withdrawn, nothing else."""
    request = regulated(prepared_by=curator)
    for restriction in StrainRestriction.objects.filter(strain__request_lines__request=request):
        end_restriction(restriction, proposer=curator, confirmer=approver)

    def cancel() -> None:
        with as_actor(curator):
            services.request_cancel(access=access_for(curator), request=request, reason="late")

    for call in (
        lambda: ship(curator, request),
        lambda: approve(curator, request),
        cancel,
        lambda: prepare(curator, request),
    ):
        refused(services.WrongState, "request_state", call)


def test_nothing_is_confirmed_or_withdrawn_that_was_not_prepared(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated()

    def confirm_anything() -> None:
        with as_actor(manager):
            services.request_confirm_shipment(
                access=access_for(manager), request=request, preparation=request.public_id
            )

    refused(services.WrongState, "request_state", confirm_anything)
    refused(services.WrongState, "request_state", lambda: withdraw(curator, request))


def test_a_shipped_request_is_not_prepared_confirmed_or_withdrawn_again(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    preparation = open_preparation(request)
    confirm(manager, request)
    refused(services.WrongState, "request_state", lambda: confirm(manager, request, preparation))
    refused(services.WrongState, "request_state", lambda: withdraw(curator, request))
    refused(services.WrongState, "request_state", lambda: prepare(curator, request))


# The gates again, on the confirmation day.


def test_a_permit_that_expires_between_preparation_and_confirmation_blocks_it(
    *,
    approver: User,
    curator: User,
    manager: User,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
    regulated: Regulated,
) -> None:
    """The § 17a notice holds through today: prepared and confirmable today, blocked
    tomorrow, and nothing has left."""
    strain = supply(mockia, restrictions=[RAT], vials=6)
    add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE, expires_on=permit_today())
    request = regulated(strain=strain, prepared_by=curator)
    with time_machine.travel(timezone.now() + timedelta(days=1), tick=False):
        error = refused(
            services.ShipmentBlocked, "shipment_blocked", lambda: confirm(manager, request)
        )
    assert "notice to SÚJB" in error.detail
    request.refresh_from_db()
    assert request.status == RequestStatus.AWAITING_CONFIRMATION
    confirm(manager, request)  # still today: the notice holds
    request.refresh_from_db()
    assert request.status == RequestStatus.SHIPPED


def test_a_permit_that_expired_before_the_preparation_blocks_the_preparation(
    *,
    curator: User,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
    regulated: Regulated,
) -> None:
    strain = supply(mockia, restrictions=[RAT], vials=6)
    add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE, expires_on=permit_today())
    request = regulated(strain=strain)
    with time_machine.travel(timezone.now() + timedelta(days=1), tick=False):
        refused(services.ShipmentBlocked, "shipment_blocked", lambda: prepare(curator, request))


def test_a_batch_held_after_the_preparation_blocks_the_confirmation(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    batch = reserved(request)[0].batch
    with as_actor(curator):
        lineage.batch_hold(access=access_for(curator), batch=batch, reason="Contamination seen.")
    error = refused(services.ShipmentBlocked, "shipment_blocked", lambda: confirm(manager, request))
    assert "0 of its 1 reserved vials may still go out" in error.detail


def test_a_risk_group_raised_after_the_preparation_makes_the_exemption_refused_at_confirmation(
    *, curator: User, manager: User, approver: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    strain = request.lines.get().strain
    with as_actor(approver):
        strains.strain_set_risk_group(
            access=access_for(approver), strain=strain, risk_group=2, reason="Reassessed."
        )
    refused(
        services.InvalidDistribution,
        "not_exempt",
        lambda: confirm(manager, request),
        attr="classification_basis",
    )


# Withdrawal.


@pytest.mark.parametrize("by", ["curator", "manager"])
def test_the_preparer_or_another_person_withdraws_and_the_preparation_stays(
    *, by: str, curator: User, manager: User, regulated: Regulated
) -> None:
    actor = {"curator": curator, "manager": manager}[by]
    request = regulated(prepared_by=curator)
    preparation = open_preparation(request)
    facts = {f: getattr(preparation, f) for f in PACKAGE_FIELDS}
    start = last_pk()
    withdraw(actor, request, "The courier cannot come this week.")

    request.refresh_from_db()
    assert request.status == RequestStatus.APPROVED
    preparation.refresh_from_db()
    assert (preparation.withdrawn_by, preparation.withdraw_reason) == (
        actor,
        "The courier cannot come this week.",
    )
    assert preparation.withdrawn_at is not None
    assert {f: getattr(preparation, f) for f in PACKAGE_FIELDS} == facts
    assert reserved(request)  # the vials stay reserved
    [event] = events_since(start)
    assert (event.event_type, event.reason) == (
        "request_shipment_withdrawn",
        "The courier cannot come this week.",
    )
    assert event.changes == {
        "status": ["awaiting_confirmation", "approved"],
        "preparation": [str(preparation.public_id), None],
    }
    # Prepared again, by anyone; both rows stay.
    prepare(manager, request)
    assert ShipmentPreparation.objects.filter(request=request).count() == 2


def test_a_withdrawal_needs_a_reason(*, curator: User, regulated: Regulated) -> None:
    request = regulated(prepared_by=curator)
    refused(RuleViolation, "reason_required", lambda: withdraw(curator, request, "  "), "reason")


# The database: the same rules, whoever writes.


def sql(statement: str, params: list[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(statement, params)


def confirmation_row(
    request: DistributionRequest, preparation: ShipmentPreparation, **changes: Any
) -> Shipment:
    values: dict[str, Any] = {
        **{f: getattr(preparation, f) for f in PACKAGE_FIELDS},
        "lab": request.lab,
        "request": request,
        "preparation": preparation,
        "classified_by_id": preparation.prepared_by_id,
        "classified_at": preparation.prepared_at,
        "shipped_at": timezone.now(),
        **changes,
    }
    return Shipment.objects.create(**values)


@pytest.mark.parametrize(
    ("who", "message"),
    [
        ("curator", "nobody confirms their own preparation"),
        ("approver", "nobody confirms the shipment of their own approval"),
    ],
)
def test_the_table_refuses_a_confirmation_by_the_preparer_or_the_approver(
    *, who: str, message: str, curator: User, approver: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    preparation = open_preparation(request)
    shipper = {"curator": curator, "approver": approver}[who]
    with pytest.raises(IntegrityError, match=message), transaction.atomic():
        confirmation_row(request, preparation, shipped_by=shipper)


@pytest.mark.parametrize(
    "changes",
    [
        {"carrier": "Another Courier"},
        {"tracking_number": "EX 2"},
        {"coolant": "cold_packs"},
        {"classified_at": "2026-01-01T00:00:00Z"},
        {
            "transport_class": TransportClass.UN3373,
            "packing_instruction": PackingInstruction.P650,
            "classification_basis": ClassificationBasis.INDICATIVE_LIST,
        },
    ],
)
def test_the_table_refuses_a_confirmation_that_differs_from_the_preparation(
    *, changes: dict[str, Any], curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    preparation = open_preparation(request)
    with (
        pytest.raises(IntegrityError, match="a confirmed shipment is what was prepared"),
        transaction.atomic(),
    ):
        confirmation_row(request, preparation, shipped_by=manager, **changes)


def test_the_table_refuses_a_confirmation_by_another_classifier(
    *, curator: User, manager: User, approver: User, regulated: Regulated
) -> None:
    """classified_by is the preparer: nobody else is written in as the one who classified."""
    request = regulated(prepared_by=curator)
    preparation = open_preparation(request)
    with (
        pytest.raises(IntegrityError, match="a confirmed shipment is what was prepared"),
        transaction.atomic(),
    ):
        confirmation_row(request, preparation, shipped_by=manager, classified_by_id=approver.pk)


def test_the_table_refuses_a_regulated_shipment_without_a_preparation(
    *, manager: User, regulated: Regulated
) -> None:
    request = regulated()
    contact = Contact.objects.create(lab=request.lab, name="Jan Odpovědný", phone="+420 555 000")
    with (
        pytest.raises(IntegrityError, match="leaves only with a confirmed preparation"),
        transaction.atomic(),
    ):
        Shipment.objects.create(
            lab=request.lab,
            request=request,
            transport_class=TransportClass.NOT_SUBJECT,
            classification_basis=ClassificationBasis.EXEMPT_NON_PATHOGENIC,
            classified_by=manager,
            classified_at=timezone.now(),
            packing_instruction=PackingInstruction.TRIPLE,
            responsible=contact,
            carrier="Example Courier",
            shipped_by=manager,
            shipped_at=timezone.now(),
        )


def test_the_table_refuses_a_confirmation_of_a_withdrawn_or_foreign_preparation(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    withdrawn = open_preparation(request)
    withdraw(curator, request)
    prepare(curator, request)
    other = regulated(prepared_by=curator)
    for preparation in (withdrawn, open_preparation(other)):
        with (
            pytest.raises(IntegrityError, match="confirms the open preparation of its request"),
            transaction.atomic(),
        ):
            confirmation_row(request, preparation, shipped_by=manager)


def test_the_table_refuses_a_confirmation_of_a_request_not_awaiting_it(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    preparation = open_preparation(request)
    sql(
        "UPDATE distribution_shipmentpreparation SET withdrawn_at = clock_timestamp(),"
        " withdrawn_by_id = prepared_by_id, withdraw_reason = 'r' WHERE id = %s",
        [preparation.pk],
    )
    sql(
        "UPDATE distribution_distributionrequest SET status = 'approved' WHERE id = %s",
        [request.pk],
    )
    with (
        pytest.raises(IntegrityError, match="a shipment is of an approved request"),
        transaction.atomic(),
    ):
        confirmation_row(request, preparation, shipped_by=manager)


def test_a_preparation_changes_only_once_when_it_is_withdrawn_and_never_goes(
    *, curator: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    preparation = open_preparation(request)
    for statement in (
        "UPDATE distribution_shipmentpreparation SET carrier = 'Other' WHERE id = %s",
        "UPDATE distribution_shipmentpreparation SET prepared_at = prepared_at"
        " - interval '1 day' WHERE id = %s",
    ):
        with (
            pytest.raises(IntegrityError, match="changes once, when it is withdrawn"),
            transaction.atomic(),
        ):
            sql(statement, [preparation.pk])
    with pytest.raises(IntegrityError, match="never deleted"), transaction.atomic():
        sql("DELETE FROM distribution_shipmentpreparation WHERE id = %s", [preparation.pk])
    withdraw(curator, request)
    with (
        pytest.raises(IntegrityError, match="changes once, when it is withdrawn"),
        transaction.atomic(),
    ):
        sql(
            "UPDATE distribution_shipmentpreparation SET withdraw_reason = 'Other' WHERE id = %s",
            [preparation.pk],
        )


def test_a_confirmed_preparation_is_not_withdrawn(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    preparation = open_preparation(request)
    confirm(manager, request)
    with (
        pytest.raises(IntegrityError, match="a confirmed preparation is not withdrawn"),
        transaction.atomic(),
    ):
        sql(
            "UPDATE distribution_shipmentpreparation SET withdrawn_at = clock_timestamp(),"
            " withdrawn_by_id = prepared_by_id, withdraw_reason = 'r' WHERE id = %s",
            [preparation.pk],
        )


def test_a_shipment_is_prepared_only_for_an_approved_request(
    *, curator: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    preparation = open_preparation(request)
    contact = Contact.objects.create(lab=request.lab, name="Jan Odpovědný", phone="+420 555 000")
    with (
        pytest.raises(IntegrityError, match="prepared for an approved request"),
        transaction.atomic(),
    ):
        ShipmentPreparation.objects.create(
            **{f: getattr(preparation, f) for f in PACKAGE_FIELDS if f != "responsible"},
            responsible=contact,
            lab=request.lab,
            request=request,
            prepared_by=curator,
            prepared_at=timezone.now(),
        )


def test_the_open_preparation_index_decides_when_a_writer_skipped_the_locks(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    """A preparation inserted right before the service's own, past every lock: the partial
    unique index refuses the second, and the service answers a conflict and writes nothing."""
    request = regulated()

    def competitor() -> None:
        contact = Contact.objects.create(lab=request.lab, name="Eva Jiná", phone="+420 555 000")
        ShipmentPreparation.objects.create(
            lab=request.lab,
            request=request,
            transport_class=TransportClass.NOT_SUBJECT,
            classification_basis=ClassificationBasis.EXEMPT_NON_PATHOGENIC,
            packing_instruction=PackingInstruction.TRIPLE,
            responsible=contact,
            carrier="Example Courier",
            prepared_by=manager,
            prepared_at=timezone.now(),
        )

    events = last_pk()
    with run_before(services, "_save", competitor), pytest.raises(services.PreparedMeanwhile):
        prepare(curator, request)
    request.refresh_from_db()
    assert request.status == RequestStatus.APPROVED
    assert last_pk() == events

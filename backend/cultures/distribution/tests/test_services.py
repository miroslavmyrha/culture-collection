"""Distribution changes only through its services: requesters and their permits, requests with
pinned lines, MTA acceptances, approval with its reservation, rejection and cancellation. Each
records its events (the line and vial ones with their strain), contacts stay out of every
event, and a refusal changes nothing and records nothing."""

import hashlib
from collections.abc import Callable
from datetime import date, timedelta

import pytest

from cultures.audit.context import AuditContext, MissingAuditContext
from cultures.audit.models import AuditEvent
from cultures.audit.registry import EVENT_TYPES
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import DomainError, Forbidden, RuleViolation
from cultures.deposits import services as deposits
from cultures.deposits.models import Contact, Deposit, DepositTerms, MtaTemplate
from cultures.deposits.tests.support import DUAL_USE, terms
from cultures.distribution import services
from cultures.distribution.models import (
    LinePermit,
    PermitKind,
    RequestCounter,
    Requester,
    RequestLine,
    RequestStatus,
    ReservationEnd,
    VialReservation,
)
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.test_lock_invariant import public_services
from cultures.lineage import services as lineage
from cultures.lineage.models import Vial, VialStatus
from cultures.lineage.tests.support import pass_all, preserve
from cultures.strains import services as strains
from cultures.strains.models import Strain
from cultures.strains.tests.conftest import new_strain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import (
    PDF,
    PNG,
    SCIENTIST,
    MakeRequester,
    Supply,
    accept_mtas,
    add_permit,
    approve,
    as_actor,
    new_request,
    permit_input,
    requester_input,
    reserved,
    snapshot,
    submit,
)

pytestmark = pytest.mark.django_db


def refused(
    error: type[DomainError], code: str, call: Callable[[], object], attr: str | None = None
) -> DomainError:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == (code, attr)
    assert snapshot() == before
    return raised.value


def events_since(pk: int) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(pk__gt=pk).order_by("pk"))


def last_pk() -> int:
    return AuditEvent.objects.order_by("-pk").values_list("pk", flat=True).first() or 0


# Requesters.


def test_a_curator_adds_a_requester_and_its_contact_stays_out_of_the_event(
    as_curator: AuditContext, curator: User, lab: Lab
) -> None:
    requester = services.requester_create(
        access=access_for(curator),
        lab=lab,
        data=requester_input(institution=" Example  Institute "),
    )
    requester.refresh_from_db()
    contact = Contact.objects.get(pk=requester.contact_id)
    assert (requester.institution, contact.name, contact.postal_address) == (
        "Example Institute",
        "Petra Ukázková",
        "Mikrobiologická laboratoř\nTestovací 5\n602 00 Brno",
    )
    event = AuditEvent.objects.get(event_type="requester_created")
    assert (
        event.changes["name"]
        == event.changes["email"]
        == event.changes["postal_address"]
        == "changed"
    )
    assert "Petra" not in str(event.changes)
    assert event.changes["institution"] == [None, "Example Institute"]
    assert (event.lab_id, event.strain_id) == (lab.pk, None)


@pytest.mark.parametrize(
    ("changes", "attr"),
    [
        ({"institution": "  "}, "institution"),
        ({"country": "XX"}, "country"),
        ({"lab_evidence": " "}, "lab_evidence"),
        ({"contact": services.ContactInput("Petra", "a@b", "")}, "contact.postal_address"),
        ({"contact": services.ContactInput(" ", "", "Lab 1")}, "contact.name"),
        ({"contact": services.ContactInput("Petra", "not-an-address", "Lab 1")}, "contact.email"),
    ],
)
def test_a_requester_needs_an_institution_a_laboratory_and_a_delivery_address(
    as_curator: AuditContext, curator: User, lab: Lab, changes: dict[str, object], attr: str
) -> None:
    refused(
        services.InvalidDistribution,
        "invalid",
        lambda: services.requester_create(
            access=access_for(curator), lab=lab, data=requester_input(**changes)
        ),
        attr,
    )


def test_a_laboratory_confirmed_tomorrow_is_refused(
    as_curator: AuditContext, curator: User, lab: Lab
) -> None:
    tomorrow = permit_today() + timedelta(days=1)
    refused(
        services.InvalidDistribution,
        "invalid",
        lambda: services.requester_create(
            access=access_for(curator), lab=lab, data=requester_input(lab_confirmed_on=tomorrow)
        ),
        "lab_confirmed_on",
    )


def test_a_changed_requester_records_what_changed_and_the_same_values_record_nothing(
    as_curator: AuditContext, curator: User, requester: Requester
) -> None:
    start = last_pk()
    data = requester_input(
        country="SK",
        contact=services.ContactInput(
            SCIENTIST.name, "petra@example.org", SCIENTIST.postal_address
        ),
    )
    services.requester_update(access=access_for(curator), requester=requester, data=data)
    services.requester_update(access=access_for(curator), requester=requester, data=data)
    [event] = events_since(start)
    assert event.event_type == "requester_changed"
    assert event.changes == {"email": "changed", "country": ["CZ", "SK"]}


def test_an_erased_requester_is_not_changed_and_gets_no_request(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    strain = supply()
    deposits.contact_erase(contact=requester.contact, reason="erasure request 2026-1")
    refused(
        services.ContactErased,
        "contact_erased",
        lambda: services.requester_update(
            access=access_for(curator), requester=requester, data=requester_input()
        ),
    )
    refused(
        services.InvalidDistribution,
        "invalid",
        lambda: services.request_submit(
            access=access_for(curator), lab=lab, data=new_request(requester, [(strain, 1)])
        ),
        "requester",
    )


# Recipient permits and documents.


def test_a_permit_is_recorded_with_its_file_and_ended_once(
    as_curator: AuditContext, curator: User, requester: Requester
) -> None:
    permit = add_permit(curator, requester, PermitKind.SUJB_VRAT)
    assert permit.document.sha256 == hashlib.sha256(PDF).hexdigest()
    assert (permit.document.content_type, permit.document.size_bytes) == (
        "application/pdf",
        len(PDF),
    )
    added = AuditEvent.objects.get(event_type="recipient_permit_added")
    assert added.changes["document"][1]["sha256"] == permit.document.sha256
    services.permit_end(
        access=access_for(curator), permit=permit, ended_on=date(2026, 6, 1), reason="revoked"
    )
    ended = AuditEvent.objects.get(event_type="recipient_permit_ended")
    assert (ended.reason, ended.changes) == ("revoked", {"ended_on": [None, "2026-06-01"]})
    refused(
        services.PermitEnded,
        "permit_ended",
        lambda: services.permit_end(
            access=access_for(curator), permit=permit, ended_on=date(2026, 6, 2), reason="again"
        ),
    )
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.permit_end(
            access=access_for(curator), permit=permit, ended_on=date(2026, 6, 2), reason=" "
        ),
        "reason",
    )


def test_a_permit_does_not_end_before_it_started(
    as_curator: AuditContext, curator: User, requester: Requester
) -> None:
    permit = add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE)
    refused(
        services.InvalidDistribution,
        "invalid",
        lambda: services.permit_end(
            access=access_for(curator), permit=permit, ended_on=date(2025, 12, 31), reason="r"
        ),
        "ended_on",
    )


@pytest.mark.parametrize(
    ("kind", "changes", "attr"),
    [
        (PermitKind.SUJB_VRAT, {"covers": " "}, "covers"),
        (PermitKind.PLANT_HEALTH_LOA, {"quantity_allowed": None}, "quantity_allowed"),
        (PermitKind.PLANT_HEALTH_LOA, {"sendings_allowed": 0}, "sendings_allowed"),
        (PermitKind.SUJB_RAT_NOTICE, {"quantity_allowed": 3}, "quantity_allowed"),
        (PermitKind.SUJB_RAT_NOTICE, {"gmo_category": 1}, "gmo_category"),
        (PermitKind.GMO_CONTAINED_USE, {"gmo_category": None}, "gmo_category"),
        (PermitKind.GMO_CONTAINED_USE, {"gmo_category": 5}, "gmo_category"),
        (PermitKind.PATHOGEN_WORK_PERMIT, {"risk_group": None}, "risk_group"),
        (PermitKind.SUJB_RAT_NOTICE, {"risk_group": 2}, "risk_group"),
        (
            PermitKind.SUJB_RAT_NOTICE,
            {"endorsement_reference": "E/1", "endorsed_on": date(2026, 1, 2)},
            "endorsement_reference",
        ),
        (PermitKind.PLANT_HEALTH_LOA, {"endorsement_reference": "E/1"}, "endorsed_on"),
        (PermitKind.PLANT_HEALTH_LOA, {"endorsed_on": date(2026, 1, 2)}, "endorsement_reference"),
        (PermitKind.SUJB_RAT_NOTICE, {"issuer": " "}, "issuer"),
        (PermitKind.SUJB_RAT_NOTICE, {"issuer_country": "XX"}, "issuer_country"),
        (PermitKind.SUJB_RAT_NOTICE, {"reference": ""}, "reference"),
        (PermitKind.SUJB_RAT_NOTICE, {"expires_on": date(2025, 1, 1)}, "expires_on"),
        (PermitKind.SUJB_RAT_NOTICE, {"document": services.DocumentInput(b"")}, "file"),
        (PermitKind.SUJB_RAT_NOTICE, {"document": services.DocumentInput(b"<html>")}, "file"),
        (
            PermitKind.SUJB_RAT_NOTICE,
            {"document": services.DocumentInput(PDF + b"x" * (10 * 1024 * 1024))},
            "file",
        ),
    ],
)
def test_permit_errors_name_their_field_and_change_nothing(
    *,
    as_curator: AuditContext,
    curator: User,
    requester: Requester,
    kind: PermitKind,
    changes: dict[str, object],
    attr: str,
) -> None:
    refused(
        services.InvalidDistribution,
        "invalid",
        lambda: services.permit_add(
            access=access_for(curator), requester=requester, data=permit_input(kind, **changes)
        ),
        attr,
    )


def test_a_png_is_a_document_too(
    as_curator: AuditContext, curator: User, requester: Requester
) -> None:
    permit = add_permit(
        curator, requester, PermitKind.SUJB_RAT_NOTICE, document=services.DocumentInput(PNG)
    )
    assert permit.document.content_type == "image/png"


# Requests.


def test_a_request_pins_the_terms_and_mta_in_force_and_takes_the_next_number(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mta: MtaTemplate,
    mockia: Taxon,
) -> None:
    first, second = supply(), supply(mockia)
    start = last_pk()
    request = submit(curator, lab, requester, [(first, 2), (second, 1)])
    again = submit(curator, lab, requester, [(first, 1)])
    year = permit_today().year
    assert (request.year, request.number, again.number) == (year, 1, 2)
    assert RequestCounter.objects.get(lab=lab, year=year).last_number == 2
    assert (request.destination_country, request.status, request.submitted_by) == (
        "CZ",
        RequestStatus.SUBMITTED,
        curator,
    )
    lines = list(request.lines.order_by("pk"))
    for line, strain in zip(lines, (first, second), strict=True):
        assert line.terms == DepositTerms.objects.get(deposit__strain=strain, is_active=True)
        assert line.mta == mta
    recorded = events_since(start)
    assert [e.event_type for e in recorded[:3]] == [
        "request_submitted",
        "request_line_added",
        "request_line_added",
    ]
    assert recorded[0].strain_id is None
    assert [e.strain_id for e in recorded[1:3]] == [first.public_id, second.public_id]
    assert recorded[1].changes["mta"][1] == {
        "public_id": str(mta.public_id),
        "code": "STD",
        "version": 1,
    }


@pytest.mark.parametrize(
    ("changes", "attr"),
    [
        ({"end_use": " "}, "end_use"),
        ({"containment_level": 0}, "containment_level"),
        ({"containment_level": 5}, "containment_level"),
    ],
)
def test_request_errors_name_their_field(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    changes: dict[str, object],
    attr: str,
) -> None:
    strain = supply()
    refused(
        services.InvalidDistribution,
        "invalid",
        lambda: services.request_submit(
            access=access_for(curator),
            lab=lab,
            data=new_request(requester, [(strain, 1)], **changes),
        ),
        attr,
    )


def test_lines_are_checked_one_by_one(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    strain = supply()
    access = access_for(curator)
    cases = [
        ([], "lines"),
        ([(strain, 1), (strain, 2)], "lines.1.strain"),
        ([(strain, 0)], "lines.0.quantity"),
        ([(strain, 51)], "lines.0.quantity"),
    ]
    for lines, attr in cases:
        refused(
            services.InvalidDistribution,
            "invalid",
            lambda lines=lines: services.request_submit(  # type: ignore[misc]
                access=access, lab=lab, data=new_request(requester, lines)
            ),
            attr,
        )


def test_a_strain_without_terms_cannot_be_asked_for(
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    make_strain_direct: Strain,
) -> None:
    refused(
        services.InvalidDistribution,
        "no_terms",
        lambda: services.request_submit(
            access=access_for(curator),
            lab=lab,
            data=new_request(requester, [(make_strain_direct, 1)]),
        ),
        "lines.0.strain",
    )


@pytest.fixture
def make_strain_direct(lab: Lab, curator: User, exempli: Taxon) -> Strain:
    """A strain created without a deposit (the way the catalogue import will): no terms."""
    with as_actor(curator):
        return strains.strain_create(access=access_for(curator), lab=lab, data=new_strain(exempli))


@pytest.mark.parametrize(
    ("regulated", "code"), [(False, "export_not_supported"), (True, "export_of_regulated_strain")]
)
def test_nothing_is_asked_for_outside_the_eu(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    make_requester: MakeRequester,
    supply: Supply,
    mockia: Taxon,
    regulated: bool,
    code: str,
) -> None:
    strain = supply(mockia, restrictions=[DUAL_USE]) if regulated else supply()
    abroad = make_requester(country="CH")
    refused(
        services.DestinationRefused,
        code,
        lambda: services.request_submit(
            access=access_for(curator), lab=lab, data=new_request(abroad, [(strain, 1)])
        ),
        "requester",
    )


# MTA acceptances.


def test_an_acceptance_keeps_its_signer_as_a_contact_and_its_signed_copy(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    [acceptance] = accept_mtas(curator, request)
    assert acceptance.signer.name == "Karel Podpisový"
    assert acceptance.document.content == PDF
    event = AuditEvent.objects.get(event_type="mta_acceptance_recorded")
    assert event.changes["signer"] == "changed"
    assert "Karel" not in str(event.changes)
    refused(services.AcceptanceExists, "acceptance_exists", lambda: accept_mtas(curator, request))


def test_an_acceptance_is_of_a_version_the_request_is_pinned_to_and_only_while_it_waits(
    *,
    as_curator: AuditContext,
    curator: User,
    manager: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    with as_actor(manager):
        other = deposits.mta_template_publish(
            access=access_for(manager), lab=lab, code="OTHER", title="Other", text="Other terms."
        )
    refused(
        services.InvalidDistribution,
        "invalid",
        lambda: accept_mtas(curator, request, mta_id=other.pk),
        "mta",
    )
    services.request_reject(access=access_for(curator), request=request, reason="no permit")
    refused(services.WrongState, "request_state", lambda: accept_mtas(curator, request))


# Approval and the reservation (D19).


def test_approval_reserves_vials_records_the_permits_and_names_each_strain(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
) -> None:
    strain = supply(risk_group=2)
    work = add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT)
    request = submit(curator, lab, requester, [(strain, 3)])
    accept_mtas(curator, request)
    start = last_pk()
    approve(curator, request)
    request.refresh_from_db()
    assert (request.status, request.decided_by, request.decision_reason) == (
        RequestStatus.APPROVED,
        curator,
        "",
    )
    vials = reserved(request)
    assert len(vials) == 3
    assert {v.status for v in vials} == {VialStatus.RESERVED}
    assert list(LinePermit.objects.values_list("permit_id", flat=True)) == [work.pk]
    recorded = events_since(start)
    assert [e.event_type for e in recorded] == [
        "vial_status_changed",
        "vial_status_changed",
        "vial_status_changed",
        "request_line_reserved",
        "request_approved",
    ]
    assert {e.strain_id for e in recorded[:4]} == {strain.public_id}
    assert recorded[0].reason == f"Reserved for request {request.label}."
    assert recorded[3].changes["vials"][1] == [str(v.public_id) for v in vials]
    assert recorded[4].strain_id is None


def test_only_released_distribution_vials_of_the_strain_are_reserved(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
) -> None:
    strain = supply(vials=2)
    seed = supply(mockia, purpose="seed")  # another strain's seed stock never counts
    passage0 = strain.passages.get(number=0)
    with as_actor(curator):
        preserve(curator, passage0, vial_count=4, purpose="seed")
        preserve(curator, passage0, vial_count=4)  # distribution stock, pending its checks
    request = submit(curator, lab, requester, [(strain, 3)])
    accept_mtas(curator, request)
    refused(services.RequestBlocked, "request_blocked", lambda: approve(curator, request))
    assert seed.pk != strain.pk
    small = submit(curator, lab, requester, [(strain, 2)])
    accept_mtas(curator, small)
    approve(curator, small)
    assert {(v.batch.purpose, v.batch.status) for v in reserved(small)} == {
        ("distribution", "released")
    }


def test_a_blocker_refuses_the_approval_and_names_every_finding(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    request = submit(curator, lab, requester, [(supply(), 9)])
    error = refused(services.RequestBlocked, "request_blocked", lambda: approve(curator, request))
    assert "9" in error.detail and "MTA STD version 1" in error.detail


def test_a_regulated_line_needs_a_manager_and_a_reason(
    *,
    as_curator: AuditContext,
    curator: User,
    manager: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
) -> None:
    request = submit(curator, lab, requester, [(supply(mockia, restrictions=[DUAL_USE]), 1)])
    accept_mtas(curator, request)
    refused(
        services.ManagerRequired,
        "manager_approval_required",
        lambda: approve(curator, request, reason="ok"),
    )
    refused(RuleViolation, "reason_required", lambda: approve(manager, request), "reason")
    approve(manager, request, reason="Dual-use inside the EU: no licence needed.")
    request.refresh_from_db()
    assert (request.decided_by, request.decision_reason) == (
        manager,
        "Dual-use inside the EU: no licence needed.",
    )
    event = AuditEvent.objects.get(event_type="request_approved")
    assert event.changes["findings"][1] == ["regulated"]


def test_a_decided_request_is_not_decided_again(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    accept_mtas(curator, request)
    approve(curator, request)
    refused(services.WrongState, "request_state", lambda: approve(curator, request))
    refused(
        services.WrongState,
        "request_state",
        lambda: services.request_reject(access=access_for(curator), request=request, reason="r"),
    )


def test_a_rejection_needs_a_reason_and_reserves_nothing(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.request_reject(access=access_for(curator), request=request, reason=""),
        "reason",
    )
    services.request_reject(
        access=access_for(curator), request=request, reason="No microbiology laboratory."
    )
    request.refresh_from_db()
    assert (request.status, request.decision_reason, request.decided_by) == (
        RequestStatus.REJECTED,
        "No microbiology laboratory.",
        curator,
    )
    assert not VialReservation.objects.exists()
    event = AuditEvent.objects.get(event_type="request_rejected")
    assert event.reason == "No microbiology laboratory."


def test_a_cancellation_ends_the_reservations_and_frees_the_vials(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    strain = supply()
    request = submit(curator, lab, requester, [(strain, 2)])
    accept_mtas(curator, request)
    approve(curator, request)
    vials = reserved(request)
    start = last_pk()
    services.request_cancel(
        access=access_for(curator), request=request, reason="The requester withdrew it."
    )
    request.refresh_from_db()
    assert (request.status, request.cancelled_by, request.decided_by) == (
        RequestStatus.CANCELLED,
        curator,
        curator,
    )
    assert reserved(request) == []
    assert {v.status for v in Vial.objects.filter(pk__in=[v.pk for v in vials])} == {
        VialStatus.AVAILABLE
    }
    assert set(VialReservation.objects.values_list("end_reason", flat=True)) == {
        ReservationEnd.CANCELLED
    }
    recorded = events_since(start)
    assert [e.event_type for e in recorded] == [
        "vial_status_changed",
        "vial_status_changed",
        "request_line_released",
        "request_cancelled",
    ]
    assert {e.strain_id for e in recorded[:3]} == {strain.public_id}
    assert recorded[-1].reason == "The requester withdrew it."
    refused(
        services.WrongState,
        "request_state",
        lambda: services.request_cancel(access=access_for(curator), request=request, reason="r"),
    )


def test_a_waiting_request_is_cancelled_without_reservations(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    services.request_cancel(access=access_for(curator), request=request, reason="duplicate")
    request.refresh_from_db()
    assert (request.status, request.decided_by) == (RequestStatus.CANCELLED, None)


def test_a_reserved_vial_leaves_its_state_only_through_its_request(
    *,
    as_curator: AuditContext,
    curator: User,
    technician: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    accept_mtas(curator, request)
    approve(curator, request)
    [vial] = reserved(request)
    refused(
        lineage.VialReserved,
        "vial_reserved",
        lambda: lineage.vial_transition(
            access=access_for(technician), vial=vial, status=VialStatus.TO_DESTROY, reason="r"
        ),
    )


# Who may, and the audit context.


SCENARIOS: dict[str, Callable[..., object]] = {
    "requester_create": lambda a, f: services.requester_create(
        access=a, lab=f["lab"], data=requester_input()
    ),
    "requester_update": lambda a, f: services.requester_update(
        access=a, requester=f["requester"], data=requester_input(country="SK")
    ),
    "permit_add": lambda a, f: services.permit_add(
        access=a, requester=f["requester"], data=permit_input()
    ),
    "permit_end": lambda a, f: services.permit_end(
        access=a, permit=f["permit"], ended_on=date(2026, 6, 1), reason="revoked"
    ),
    "request_submit": lambda a, f: services.request_submit(
        access=a, lab=f["lab"], data=new_request(f["requester"], [(f["strain"], 1)])
    ),
    "acceptance_record": lambda a, f: services.acceptance_record(
        access=a,
        request=f["request"],
        data=services.AcceptanceInput(
            mta_id=f["mta"].pk,
            signer=services.ContactInput("Karel Podpisový"),
            signer_role="head_of_institution",  # type: ignore[arg-type]
            authorised_signatory=True,
            accepted_on=date(2026, 10, 2),
            document=services.DocumentInput(PDF),
        ),
    ),
    "request_approve": lambda a, f: services.request_approve(access=a, request=f["accepted"]),
    "request_reject": lambda a, f: services.request_reject(
        access=a, request=f["request"], reason="r"
    ),
    "request_cancel": lambda a, f: services.request_cancel(
        access=a, request=f["approved"], reason="r"
    ),
}
NOT_A_WRITE = {"document_type", "normalised"}


def test_every_service_has_a_scenario_here() -> None:
    found = public_services(services)
    assert {"request_submit", "request_approve"} <= found
    assert found - NOT_A_WRITE == set(SCENARIOS)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_line_event_names_its_strain_and_every_event_its_lab(
    *, name: str, as_curator: AuditContext, curator: User, world: dict[str, object]
) -> None:
    start = last_pk()
    SCENARIOS[name](access_for(curator), world)
    recorded = events_since(start)
    assert recorded, name
    assert {e.lab_id for e in recorded} == {world["lab"].pk}, name  # type: ignore[attr-defined]
    for event in recorded:
        about_material = event.subject_type in ("request_line", "vial")
        assert (event.strain_id is not None) == about_material, (name, event.event_type)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_a_curator_demoted_since_the_request_began_is_refused(
    *, name: str, as_curator: AuditContext, curator: User, lab: Lab, world: dict[str, object]
) -> None:
    access = access_for(curator)  # built while the curator was one
    Membership.objects.filter(user=curator, lab=lab).update(role=Role.TECHNICIAN)
    refused(Forbidden, "permission_denied", lambda: SCENARIOS[name](access, world))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_service_needs_an_audit_context(
    name: str, curator: User, world: dict[str, object]
) -> None:
    before = snapshot()
    with pytest.raises(MissingAuditContext):
        SCENARIOS[name](access_for(curator), world)
    assert snapshot() == before


def test_the_deposit_terms_replaced_after_entry_stay_pinned_on_the_line(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
) -> None:
    strain = supply()
    request = submit(curator, lab, requester, [(strain, 1)])
    deposit = Deposit.objects.get(strain=strain)
    deposits.deposit_terms_replace(
        access=access_for(curator), deposit=deposit, terms=terms(), reason="new"
    )
    line = RequestLine.objects.get(request=request)
    assert line.terms.version == 1
    assert DepositTerms.objects.get(deposit=deposit, is_active=True).version == 2


def test_approval_never_takes_seed_stock_even_when_it_is_older(
    *, as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    """Seed vials have the lowest pks here, and pk order is the pick order: only
    distributable() keeps them in the freezer (D15, OECD 11.2)."""
    strain = supply(vials=3, purpose="seed", release=False)
    passage0 = strain.passages.get(number=0)
    stock = preserve(curator, passage0, vial_count=3)
    pass_all(curator, stock)
    lineage.batch_release(access=access_for(curator), batch=stock, reason="checks passed")
    request = submit(curator, lab, requester, [(strain, 2)])
    accept_mtas(curator, request)
    approve(curator, request)
    assert {v.batch_id for v in reserved(request)} == {stock.pk}


def test_the_service_refuses_a_requester_of_another_lab(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    other_lab: Lab,
    outsider: User,
    make_requester: MakeRequester,
    supply: Supply,
) -> None:
    """The API resolves the requester in the URL's lab; the service holds the rule on its own
    for commands and seeds."""
    foreign = make_requester(lab=other_lab, actor=outsider)
    strain = supply()
    refused(
        services.InvalidDistribution,
        "invalid",
        lambda: services.request_submit(
            access=access_for(curator), lab=lab, data=new_request(foreign, [(strain, 1)])
        ),
        "requester",
    )


def test_the_cancellation_and_rejection_events_require_their_reason() -> None:
    required = {
        "request_rejected",
        "request_cancelled",
        "recipient_permit_ended",
    }
    assert {c for c in required if EVENT_TYPES[c].reason_required} == required

"""Data and helpers for the distribution tests. Fixtures: fixtures.py, imported by conftest.py.

The lab, people and taxa are the strains tests' (Mycology, MYC, one member of every role; the
invented taxa Testella, Mockia and Fictivibrio): regulated examples pair an invented taxon with
a restriction, so no real organism gets a legal status here. Requesters are invented
institutions at example.org addresses. Documents are a few bytes with a real PDF signature.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel, RowChange
from cultures.deposits.models import Contact, Use
from cultures.distribution import services
from cultures.distribution.models import (
    ClassificationBasis,
    DistributionRequest,
    Document,
    LegalForm,
    LinePermit,
    MtaAcceptance,
    PackingInstruction,
    PermitKind,
    RecipientPermit,
    RequestCounter,
    Requester,
    RequestLine,
    Shipment,
    ShipmentVial,
    SignerRole,
    TransportClass,
    VialReservation,
)
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.lineage.models import Batch, Vial, VialPlacement
from cultures.strains.models import Strain
from cultures.strains.tests.conftest import LAB_ID
from cultures.users.models import User

LAB_URL = f"/api/v1/labs/{LAB_ID}"
REQUESTERS_URL = f"{LAB_URL}/requesters/"
PERMITS_URL = f"{LAB_URL}/recipient-permits/"
DOCUMENTS_URL = f"{LAB_URL}/documents/"
REQUESTS_URL = f"{LAB_URL}/requests/"

PDF = b"%PDF-1.4\n% an invented test document\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
SCIENTIST = services.ContactInput(
    "Petra Ukázková",
    "petra.ukazkova@example.org",
    "Mikrobiologická laboratoř\nTestovací 5\n602 00 Brno",
)


def as_actor(actor: User) -> AbstractContextManager[AuditContext]:
    return audit_context(channel=Channel.API, actor=actor, request_id="req-setup")


def requester_input(**changes: Any) -> services.RequesterInput:
    values: dict[str, Any] = {
        "contact": SCIENTIST,
        "institution": "Example Institute of Microbiology",
        "legal_form": LegalForm.LEGAL_PERSON,
        "country": "CZ",
        "lab_evidence": "The institute's department page lists a BSL-2 microbiology laboratory.",
        "lab_confirmed_on": date(2026, 10, 1),
        "registration_number": "00000001",
        **changes,
    }
    return services.RequesterInput(**values)


def permit_input(
    kind: PermitKind = PermitKind.SUJB_RAT_NOTICE, **changes: Any
) -> services.PermitInput:
    values: dict[str, Any] = {
        "kind": kind,
        "issuer": "SÚJB",
        "issuer_country": "CZ",
        "reference": f"DEV/{kind}/1 (invented example)",
        "valid_from": date(2026, 1, 1),
        "document": services.DocumentInput(PDF),
        **changes,
    }
    if kind in (PermitKind.SUJB_VRAT, PermitKind.SUJB_EXCEPTION, PermitKind.PLANT_HEALTH_LOA):
        values.setdefault("covers", "Mockia vulgaris")
    if kind == PermitKind.PLANT_HEALTH_LOA:
        values.setdefault("quantity_allowed", 10)
        values.setdefault("sendings_allowed", 2)
        values.setdefault("issuer", "ÚKZÚZ")
    if kind == PermitKind.GMO_CONTAINED_USE:
        values.setdefault("gmo_category", 2)
    if kind == PermitKind.PATHOGEN_WORK_PERMIT:
        values.setdefault("risk_group", 2)
    return services.PermitInput(**values)


def add_permit(
    actor: User, requester: Requester, kind: PermitKind, **changes: Any
) -> RecipientPermit:
    with as_actor(actor):
        return services.permit_add(
            access=access_for(actor), requester=requester, data=permit_input(kind, **changes)
        )


def new_request(
    requester: Requester, lines: list[tuple[Strain, int]], **changes: Any
) -> services.NewRequest:
    values: dict[str, Any] = {
        "requester": requester,
        "use": Use.RESEARCH_NONCOMMERCIAL,
        "end_use": "Antibiotic susceptibility testing in teaching labs.",
        "containment_level": 2,
        "lines": [services.LineInput(strain, quantity) for strain, quantity in lines],
        **changes,
    }
    return services.NewRequest(**values)


def submit(
    actor: User, lab: Lab, requester: Requester, lines: list[tuple[Strain, int]], **changes: Any
) -> DistributionRequest:
    with as_actor(actor):
        return services.request_submit(
            access=access_for(actor), lab=lab, data=new_request(requester, lines, **changes)
        )


def accept_mtas(actor: User, request: DistributionRequest, **changes: Any) -> list[MtaAcceptance]:
    """An authorised acceptance of every MTA version the request's lines are pinned to."""
    mtas = sorted({line.mta_id for line in request.lines.all() if line.mta_id is not None})
    accepted = []
    with as_actor(actor):
        for mta_id in mtas:
            values: dict[str, Any] = {
                "mta_id": mta_id,
                "signer": services.ContactInput("Karel Podpisový", "karel@example.org"),
                "signer_role": SignerRole.HEAD_OF_INSTITUTION,
                "authorised_signatory": True,
                "accepted_on": date(2026, 10, 2),
                "document": services.DocumentInput(PDF),
                **changes,
            }
            accepted.append(
                services.acceptance_record(
                    access=access_for(actor),
                    request=request,
                    data=services.AcceptanceInput(**values),
                )
            )
    return accepted


def approve(actor: User, request: DistributionRequest, reason: str = "") -> DistributionRequest:
    with as_actor(actor):
        return services.request_approve(access=access_for(actor), request=request, reason=reason)


def shipment_input(**changes: Any) -> services.ShipmentInput:
    """An exempt shipment of a culture not pathogenic to humans or animals, by courier."""
    values: dict[str, Any] = {
        "transport_class": TransportClass.NOT_SUBJECT,
        "classification_basis": ClassificationBasis.EXEMPT_NON_PATHOGENIC,
        "packing_instruction": PackingInstruction.TRIPLE,
        "responsible": services.ContactInput("Jan Odpovědný", phone="+420 555 000 111"),
        "carrier": "Example Courier (invented example)",
        "tracking_number": "EX123456789CZ",
        **changes,
    }
    return services.ShipmentInput(**values)


def ship(actor: User, request: DistributionRequest, **changes: Any) -> DistributionRequest:
    with as_actor(actor):
        return services.request_ship(
            access=access_for(actor), request=request, data=shipment_input(**changes)
        )


def reserved(request: DistributionRequest) -> list[Vial]:
    return list(
        Vial.objects.filter(
            reservations__line__request=request, reservations__ended_at__isnull=True
        ).order_by("pk")
    )


TABLES = (
    Contact,
    Requester,
    Document,
    RecipientPermit,
    RequestCounter,
    DistributionRequest,
    RequestLine,
    LinePermit,
    MtaAcceptance,
    VialReservation,
    Vial,
    Shipment,
    ShipmentVial,
    Batch,
    VialPlacement,
)


def snapshot() -> tuple[Any, ...]:
    """Every table distribution writes, every event and every row change."""
    rows = tuple(list(m._default_manager.order_by("pk").values()) for m in TABLES)
    return (*rows, AuditEvent.objects.count(), RowChange.objects.count())


MakeRequester = Callable[..., Requester]
Supply = Callable[..., Strain]

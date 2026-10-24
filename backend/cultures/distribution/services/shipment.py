"""The shipment of an approved request in one step (#88), with its documents (#90)."""

import hashlib
import re
from datetime import date
from decimal import Decimal
from typing import Any

from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    PERSONAL_CHANGED,
    REQUEST_LINE_SHIPPED,
    REQUEST_SHIPPED,
    SHIPMENT_DOCUMENT_GENERATED,
)
from cultures.biosafety.policy import permit_today
from cultures.deposits.models import Contact
from cultures.labs.access import Access
from cultures.labs.permissions import Perm
from cultures.lineage import services as lineage
from cultures.lineage.models import Batch, Vial
from cultures.strains.models import Strain
from cultures.strains.selectors import regulating_restrictions

from .. import documents, policy
from ..models import (
    BASES,
    ClassificationBasis,
    Coolant,
    DistributionRequest,
    PackingInstruction,
    RequestLine,
    RequestStatus,
    ReservationEnd,
    Shipment,
    ShipmentDocument,
    ShipmentPreparation,
    ShipmentVial,
    TransportClass,
    VialReservation,
)
from ._shared import (
    LINE,
    REQUEST,
    SHIPMENT_DOCUMENT,
    _defer_reservation_checks,
    _locked_request,
    _move,
    normalised,
)
from .errors import (
    InvalidDistribution,
    SecondPersonRequired,
    ShipmentBlocked,
)
from .inputs import (
    ContactInput,
    ShipmentInput,
)

# Shipment (#88).

PHONE = re.compile(r"^[+0-9][0-9 ()-]{4,38}[0-9]$")
# The largest coolant quantity recorded, in kilograms (decimal(6, 2)).
MAX_COOLANT_KG = Decimal("9999.99")


def _checked_shipment(data: ShipmentInput) -> ShipmentInput:
    """The fields alone; what depends on the strains is checked under the locks."""
    if data.classification_basis not in BASES[data.transport_class]:
        raise InvalidDistribution(
            f"{ClassificationBasis(data.classification_basis).label} is not a basis for"
            f" {TransportClass(data.transport_class).label}.",
            attr="classification_basis",
        )
    note = data.basis_note.strip()
    if data.classification_basis == ClassificationBasis.PROFESSIONAL_JUDGEMENT and not note:
        raise InvalidDistribution(
            "Say what the judgement rests on.", code="required", attr="basis_note"
        )
    if (
        data.transport_class == TransportClass.UN3373
        and data.packing_instruction != PackingInstruction.P650
    ):
        raise InvalidDistribution("UN 3373 is packed to P650.", attr="packing_instruction")
    if data.coolant == Coolant.NONE and data.coolant_kg is not None:
        raise InvalidDistribution("Choose the coolant of this quantity.", attr="coolant")
    if data.coolant == Coolant.DRY_ICE and data.coolant_kg is None:
        raise InvalidDistribution(
            "Give the quantity of dry ice: it is marked on the package.",
            code="required",
            attr="coolant_kg",
        )
    if data.coolant_kg is not None and not Decimal(0) < data.coolant_kg <= MAX_COOLANT_KG:
        raise InvalidDistribution(
            f"Give more than 0 and at most {MAX_COOLANT_KG} kg.", attr="coolant_kg"
        )
    name = normalised(data.responsible.name)
    if not name:
        raise InvalidDistribution("Enter the responsible person.", attr="responsible_name")
    phone = " ".join(data.responsible.phone.split())
    if not PHONE.match(phone):
        raise InvalidDistribution(
            "Enter a phone number: digits, spaces, + ( ) and -.", attr="responsible_phone"
        )
    carrier = normalised(data.carrier)
    if not carrier:
        raise InvalidDistribution("Enter the carrier.", attr="carrier")
    return ShipmentInput(
        transport_class=data.transport_class,
        classification_basis=data.classification_basis,
        packing_instruction=data.packing_instruction,
        responsible=ContactInput(name, phone=phone),
        carrier=carrier,
        basis_note=note,
        coolant=data.coolant,
        coolant_kg=None if data.coolant_kg is None else data.coolant_kg.quantize(Decimal("0.01")),
        tracking_number=normalised(data.tracking_number),
    )


def _locked_strains(locked: DistributionRequest) -> tuple[list[RequestLine], list[Strain]]:
    """The request's lines and their strains, locked by pk (lock order lab, request, strain)."""
    lines = list(locked.lines.select_related("strain").order_by("pk"))
    strains = list(
        Strain.objects.select_for_update()
        .filter(pk__in=[line.strain_id for line in lines])
        .order_by("pk")
    )
    return lines, strains


def _gates_today(locked: DistributionRequest) -> date:
    """The gates on today's Czech day: any blocker refuses. Manager findings were decided at
    approval and are not asked again."""
    today = permit_today()
    blockers = policy.evaluate(locked, today).blockers
    if blockers:
        raise ShipmentBlocked(" ".join(f.sentence for f in blockers))
    return today


def _regulated(strains: list[Strain]) -> bool:
    return regulating_restrictions().filter(strain__in=strains).exists()


def _check_exempt(basis: str, strains: list[Strain]) -> None:
    """The one thing about the class the app can know: a pathogen is not exempt as
    non-pathogenic. Checked when the shipment is prepared and again when it is confirmed, as a
    risk group may rise in between."""
    if basis != ClassificationBasis.EXEMPT_NON_PATHOGENIC:
        return
    pathogens = [s.accession_number for s in strains if s.risk_group >= 2]  # noqa: PLR2004
    if pathogens:
        raise InvalidDistribution(
            f"{', '.join(map(str, pathogens))}: risk group 2 or higher is pathogenic,"
            " so the culture is not exempt as non-pathogenic.",
            code="not_exempt",
            attr="classification_basis",
        )


def _package(data: ShipmentInput, lab_id: int) -> dict[str, Any]:
    """The package's columns from the checked input, with a new contact for its person."""
    person = Contact.objects.create(
        lab_id=lab_id, name=data.responsible.name, phone=data.responsible.phone
    )
    return {
        "lab_id": lab_id,
        "transport_class": data.transport_class,
        "classification_basis": data.classification_basis,
        "basis_note": data.basis_note,
        "packing_instruction": data.packing_instruction,
        "coolant": data.coolant,
        "coolant_kg": data.coolant_kg,
        "responsible": person,
        "carrier": data.carrier,
        "tracking_number": data.tracking_number,
    }


def _package_changes(package: Shipment | ShipmentPreparation) -> dict[str, Any]:
    """The package's facts as an event records them, the responsible person as "changed"."""
    return {
        "transport_class": [None, package.transport_class],
        "classification_basis": [None, package.classification_basis],
        "basis_note": [None, package.basis_note],
        "packing_instruction": [None, package.packing_instruction],
        "coolant": [None, package.coolant],
        "coolant_kg": [None, None if package.coolant_kg is None else str(package.coolant_kg)],
        # Masked again by record_event (audit.registry.PERSONAL_FIELDS).
        "responsible": PERSONAL_CHANGED,
        "carrier": [None, package.carrier],
        "tracking_number": [None, package.tracking_number],
    }


def request_ship(
    *, access: Access, request: DistributionRequest, data: ShipmentInput
) -> DistributionRequest:
    """All the vials the approval reserved leave at once, in one transaction: the gates run
    again on the ship day (a permit may have expired since the approval), the reservations end
    as shipped, each vial is distributed (its placement closed), the shipment is recorded with
    its vials and the request is shipped. Then each distribution batch with no vial left
    available or reserved is exhausted. A request with a regulated line is refused: one person
    prepares its shipment and a second confirms it (ADR 0009, request_prepare_shipment)."""
    data = _checked_shipment(data)
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.SHIPPED, source=RequestStatus.APPROVED)
        lines, strains = _locked_strains(locked)
        # The gates first: what may not go at all is said before who else must confirm.
        today = _gates_today(locked)
        if _regulated(strains):
            raise SecondPersonRequired
        _check_exempt(data.classification_basis, strains)
        now = timezone.now()
        _defer_reservation_checks(shipment=True)
        shipment = Shipment.objects.create(
            **_package(data, locked.lab_id),
            request=locked,
            classified_by=access.user,
            classified_at=now,
            shipped_by=access.user,
            shipped_at=now,
        )
        batches = _send(access, locked, lines, shipment)
        record_event(
            REQUEST_SHIPPED,
            Change(
                REQUEST,
                locked.public_id,
                {
                    "status": [old, RequestStatus.SHIPPED],
                    "shipment": [None, str(shipment.public_id)],
                    "shipped_on": [None, today.isoformat()],
                    **_package_changes(shipment),
                },
                lab_id=locked.lab_id,
            ),
        )
        _write_documents(locked, shipment, today)
        _exhaust_emptied(locked, batches)
    return locked


def _send(
    access: Access, locked: DistributionRequest, lines: list[RequestLine], shipment: Shipment
) -> list[Batch]:
    """The shipment's vials: every open reservation of the request ends as shipped and its vial
    is distributed (lock order batch, reservation, vial, after the strains). The request is
    shipped. The caller deferred the checks at commit and created the shipment. Returns the
    batches the vials came from, locked."""
    open_rows = VialReservation.objects.filter(line__request=locked, ended_at__isnull=True)
    batch_ids = set(open_rows.values_list("vial__batch_id", flat=True))
    batches = list(
        Batch.objects.select_for_update(of=("self",))
        .select_related("strain")
        .filter(pk__in=batch_ids)
        .order_by("pk")
    )
    reservations = list(open_rows.select_for_update(of=("self",)).order_by("vial_id"))
    vials = {
        v.pk: v
        for v in Vial.objects.select_for_update(of=("self",))
        .select_related("batch__strain")
        .filter(pk__in=[r.vial_id for r in reservations])
        .order_by("pk")
    }
    now = shipment.shipped_at
    reason = f"Shipped with request {locked.label}."
    for line in lines:
        held = [r for r in reservations if r.line_id == line.pk]
        for reservation in held:
            vial = vials[reservation.vial_id]
            ShipmentVial.objects.create(shipment=shipment, line=line, vial=vial)
            reservation.ended_at, reservation.ended_by = now, access.user
            reservation.end_reason = ReservationEnd.SHIPPED
            reservation.save(update_fields=["ended_at", "ended_by", "end_reason", "updated_at"])
            lineage.vial_ship_locked(access=access, vial=vial, reason=reason)
        record_event(
            REQUEST_LINE_SHIPPED,
            Change(
                LINE,
                line.public_id,
                {
                    "shipment": [None, str(shipment.public_id)],
                    "vials": [None, [str(vials[r.vial_id].public_id) for r in held]],
                },
                lab_id=locked.lab_id,
                strain_id=line.strain.public_id,
            ),
        )
    locked.status = RequestStatus.SHIPPED
    locked.save(update_fields=["status", "updated_at"])
    return batches


def _write_documents(locked: DistributionRequest, shipment: Shipment, today: date) -> None:
    """The documents the shipment needs, rendered once from the data as it is now (after the
    vials left) and stored with their SHA-256 (documents.py). Each event holds the document's id,
    kind and SHA-256, never its text: the text names the responsible person (ADR 0009)."""
    facts = documents.gather(locked, shipment, today)
    for kind, line in documents.needs(facts):
        text = documents.render(facts, kind, line)
        document = ShipmentDocument.objects.create(
            lab_id=locked.lab_id,
            shipment=shipment,
            kind=kind,
            line=line,
            text=text,
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        )
        record_event(
            SHIPMENT_DOCUMENT_GENERATED,
            Change(
                SHIPMENT_DOCUMENT,
                document.public_id,
                {
                    "kind": [None, kind.value],
                    "shipment": [None, str(shipment.public_id)],
                    "text_sha256": [None, document.text_sha256],
                },
                lab_id=locked.lab_id,
                strain_id=None if line is None else line.strain.public_id,
            ),
        )


def _exhaust_emptied(locked: DistributionRequest, batches: list[Batch]) -> None:
    """Each distribution batch the shipment drew from, left with no vial available or reserved,
    is exhausted. Its row was locked in _send, before its vials."""
    for batch in batches:
        lineage.batch_exhaust_if_emptied_locked(
            batch=batch,
            reason=f"No vial is left to distribute after request {locked.label} was shipped.",
        )

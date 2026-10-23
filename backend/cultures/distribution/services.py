"""Every write of distribution (#18, part A): requesters and their permits, requests with their
lines, MTA acceptances, and the decisions on a request with the vials reserved at approval; the
shipment of an approved request (#88), in two steps by two people when a line is regulated (#89),
with the documents it needs written in the same transaction (#90).

Each service runs in audited_atomic() and records its events in the same transaction. Lock
order, as everywhere: the lab row first (labs.locks.lock_lab), then the request, then the
strains of its lines by pk, then their batches, then the vials (lineage keeps lab, strain,
batch, vial, box; a request sits between the lab and its strains). Under the lab lock each
service re-reads the actor's role, so a member demoted after the request built its access
object is refused. A refusal raises before anything is written, or rolls back what was, so it
changes nothing and records nothing.

Personal data (D11): the responsible scientist, an MTA's signer and a shipment's responsible
person are contacts; events record their fields as "changed", never the value. Events about a
line or its vials carry the strain (D13); a request spans strains, so its own events carry none
and each line has its own.
"""

import hashlib
import re
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, connection, transaction
from django.db.models import Model
from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    MTA_ACCEPTANCE_RECORDED,
    PERSONAL_CHANGED,
    RECIPIENT_PERMIT_ADDED,
    RECIPIENT_PERMIT_ENDED,
    REQUEST_APPROVED,
    REQUEST_CANCELLED,
    REQUEST_LINE_ADDED,
    REQUEST_LINE_RELEASED,
    REQUEST_LINE_RESERVED,
    REQUEST_LINE_SHIPPED,
    REQUEST_REJECTED,
    REQUEST_SHIPMENT_PREPARED,
    REQUEST_SHIPMENT_WITHDRAWN,
    REQUEST_SHIPPED,
    REQUEST_SUBMITTED,
    REQUESTER_CHANGED,
    REQUESTER_CREATED,
    SHIPMENT_DOCUMENT_GENERATED,
)
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import Conflict, DomainError, Forbidden, NotFound, RuleViolation
from cultures.deposits.models import Contact, DepositTerms, Use
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Perm, Role, role_has
from cultures.lineage import services as lineage
from cultures.lineage.models import Batch, Vial, VialStatus
from cultures.lineage.selectors import distributable
from cultures.strains.countries import COUNTRY_CODES
from cultures.strains.models import Strain
from cultures.strains.selectors import regulating_restrictions

from . import documents, policy
from .models import (
    ACCEPTANCE_UNIQUE,
    BASES,
    COUNTER_UNIQUE,
    MAX_DOCUMENT_BYTES,
    MAX_VIALS_PER_LINE,
    NAMES_AGENTS,
    ONE_OPEN_PREPARATION,
    ONE_OPEN_RESERVATION,
    PACKAGE_FIELDS,
    REQUEST_EDGES,
    REQUEST_NUMBER_UNIQUE,
    ClassificationBasis,
    Coolant,
    DistributionRequest,
    Document,
    DocumentType,
    LegalForm,
    LinePermit,
    MtaAcceptance,
    PackingInstruction,
    PermitKind,
    RecipientPermit,
    RequestCounter,
    Requester,
    RequestLine,
    RequestStatus,
    ReservationEnd,
    Shipment,
    ShipmentDocument,
    ShipmentPreparation,
    ShipmentVial,
    SignerRole,
    TransportClass,
    VialReservation,
)

REQUESTER, CONTACT, PERMIT, REQUEST, LINE, ACCEPTANCE, SHIPMENT_DOCUMENT = (
    "requester",
    "contact",
    "recipient_permit",
    "distribution_request",
    "request_line",
    "mta_acceptance",
    "shipment_document",
)
# A request holds at most this many strains: a bigger order is two requests.
MAX_LINES = 20
# The first bytes of each document type (the files' own signatures, never the name or header).
SIGNATURES: tuple[tuple[bytes, DocumentType], ...] = (
    (b"%PDF-", DocumentType.PDF),
    (b"\x89PNG\r\n\x1a\n", DocumentType.PNG),
    (b"\xff\xd8\xff", DocumentType.JPEG),
)


class InvalidDistribution(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class WrongState(Conflict):
    """The request is not in the state the action starts from: someone acted first."""

    default_code = "request_state"
    default_detail = "The request is no longer in this state. Reload it."


class PermitEnded(Conflict):
    default_code = "permit_ended"
    default_detail = "This permit was ended already."


class ContactErased(Conflict):
    default_code = "contact_erased"
    default_detail = "This requester's contact was erased."


class NumberTaken(Conflict):
    default_code = "request_number_taken"
    default_detail = "Another request took this number at the same moment: try again."


class AcceptanceExists(Conflict):
    default_code = "acceptance_exists"
    default_detail = "An acceptance of this MTA version is recorded for this request already."


class RequestBlocked(RuleViolation):
    default_code = "request_blocked"


class DestinationRefused(RuleViolation):
    """Nothing leaves the EU (ADR 0009 amendment of 2026-10-20)."""


class ManagerRequired(Forbidden):
    default_code = "manager_approval_required"
    default_detail = "A finding on this request needs a manager's approval."


class NotEnoughVials(Conflict):
    default_code = "not_enough_vials"


class ReservedMeanwhile(Conflict):
    default_code = "vial_reserved_meanwhile"
    default_detail = "A vial was reserved at the same moment: try again."


class ShipmentBlocked(RuleViolation):
    default_code = "shipment_blocked"


class SecondPersonRequired(RuleViolation):
    """ADR 0009: a regulated line leaves only once a second person confirmed it. The code is the
    one #88 answered; since #89 the detail says how: prepare, then another person confirms."""

    default_code = "second_person_required"
    default_detail = (
        "A regulated strain is shipped only when a second person confirms it: prepare the"
        " shipment, and a different person confirms it."
    )


class ShipInOneStep(RuleViolation):
    """Only a request with a regulated line is prepared for a second person; the others ship."""

    default_code = "ship_in_one_step"
    default_detail = "No line of this request is regulated: ship it in one step."


class ConfirmOwnApproval(Forbidden):
    """ADR 0009: the person who approved the request does not confirm its shipment."""

    default_code = "confirm_own_approval"
    default_detail = "You approved this request: a different person confirms its shipment."


class ConfirmOwnPreparation(Forbidden):
    """ADR 0009: nobody confirms the shipment they prepared."""

    default_code = "confirm_own_preparation"
    default_detail = "You prepared this shipment: a different person confirms it."


class PreparationChanged(Conflict):
    """The confirmation names the preparation the confirmer read; another one is open now."""

    default_code = "preparation_changed"
    default_detail = "The prepared shipment changed meanwhile. Read it again before you confirm."


class PreparedMeanwhile(Conflict):
    default_code = "preparation_exists"
    default_detail = "Someone prepared this shipment at the same moment. Reload the request."


@dataclass(frozen=True)
class ContactInput:
    name: str
    email: str = ""
    postal_address: str = ""
    phone: str = ""


@dataclass(frozen=True)
class RequesterInput:
    contact: ContactInput  # the responsible scientist; the postal address is the delivery address
    institution: str
    legal_form: LegalForm
    country: str
    lab_evidence: str
    lab_confirmed_on: date
    registration_number: str = ""
    seat: str = ""  # the registered office, as the business register gives it


@dataclass(frozen=True)
class DocumentInput:
    content: bytes


@dataclass(frozen=True)
class PermitInput:
    kind: PermitKind
    issuer: str
    issuer_country: str
    reference: str
    valid_from: date
    document: DocumentInput
    expires_on: date | None = None
    covers: str = ""
    quantity_allowed: int | None = None
    sendings_allowed: int | None = None
    endorsement_reference: str = ""
    endorsed_on: date | None = None
    gmo_category: int | None = None
    risk_group: int | None = None


@dataclass(frozen=True)
class LineInput:
    strain: Strain
    quantity: int


@dataclass(frozen=True)
class NewRequest:
    requester: Requester
    use: Use
    end_use: str
    containment_level: int
    lines: Sequence[LineInput]


@dataclass(frozen=True)
class AcceptanceInput:
    mta_id: int  # an MTA version pinned on a line of the request
    signer: ContactInput
    signer_role: SignerRole
    authorised_signatory: bool
    accepted_on: date
    document: DocumentInput


@dataclass(frozen=True)
class ShipmentInput:
    transport_class: TransportClass
    classification_basis: ClassificationBasis
    packing_instruction: PackingInstruction
    responsible: ContactInput  # name and phone of the person who answers for the package
    carrier: str
    basis_note: str = ""
    coolant: Coolant = Coolant.NONE
    coolant_kg: Decimal | None = None
    tracking_number: str = ""


def normalised(text: str) -> str:
    """One space between words, NFC."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _check_reason(reason: str) -> str:
    text = reason.strip()
    if not text:
        raise RuleViolation("A reason is required.", code="reason_required", attr="reason")
    return text


def _checked_contact(contact: ContactInput, prefix: str, *, address: bool) -> ContactInput:
    name = normalised(contact.name)
    if not name:
        raise InvalidDistribution("Enter the name.", attr=f"{prefix}name")
    email = contact.email.strip()
    if email and (email.count("@") != 1 or any(c.isspace() for c in email)):
        raise InvalidDistribution("Enter an e-mail address.", attr=f"{prefix}email")
    lines = [" ".join(line.split()) for line in contact.postal_address.splitlines()]
    postal = unicodedata.normalize("NFC", "\n".join(line for line in lines if line))
    if address and not postal:
        raise InvalidDistribution(
            "Enter the delivery address of the laboratory.", attr=f"{prefix}postal_address"
        )
    return ContactInput(name, email, postal)


def _checked_requester(data: RequesterInput) -> RequesterInput:
    contact = _checked_contact(data.contact, "contact.", address=True)
    institution = normalised(data.institution)
    if not institution:
        raise InvalidDistribution("Enter the institution.", attr="institution")
    if data.country not in COUNTRY_CODES:
        raise InvalidDistribution("Choose a country.", attr="country")
    evidence = data.lab_evidence.strip()
    if not evidence:
        raise InvalidDistribution(
            "Say how the microbiology laboratory was confirmed.", attr="lab_evidence"
        )
    if data.lab_confirmed_on > permit_today():
        raise InvalidDistribution("This date is in the future.", attr="lab_confirmed_on")
    return RequesterInput(
        contact=contact,
        institution=institution,
        legal_form=data.legal_form,
        country=data.country,
        lab_evidence=evidence,
        lab_confirmed_on=data.lab_confirmed_on,
        registration_number=normalised(data.registration_number),
        # One line: an address pasted from the register over several lines keeps its parts.
        seat=", ".join(part for line in data.seat.splitlines() if (part := normalised(line))),
    )


def document_type(content: bytes) -> DocumentType:
    """The type from the file's own first bytes; anything else is refused."""
    for signature, kind in SIGNATURES:
        if content.startswith(signature):
            return kind
    raise InvalidDistribution("Give the file as a PDF, PNG or JPEG.", attr="file")


def _checked_document(data: DocumentInput) -> DocumentInput:
    if not data.content:
        raise InvalidDistribution("The file is empty.", attr="file")
    if len(data.content) > MAX_DOCUMENT_BYTES:
        raise InvalidDistribution(
            f"The file is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB.", attr="file"
        )
    document_type(data.content)
    return data


# Under the lab lock.


def _require(access: Access, lab_id: int, perm: Perm) -> None:
    """The actor's role as committed now (caller holds the lab lock), not as the request began."""
    role = (
        Membership.objects.filter(lab_id=lab_id, user=access.user, user__is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    if role is None or not role_has(Role(role), perm):
        raise Forbidden


def _save(obj: Model, errors: dict[str, DomainError]) -> None:
    """The unique constraints are the final arbiter: a check before saving can race."""
    try:
        with transaction.atomic():
            obj.save()
    except IntegrityError as exc:
        diag = getattr(exc.__cause__, "diag", None)
        error = errors.get(str(getattr(diag, "constraint_name", "")))
        if error is not None:
            raise error from exc
        raise


def _locked[T: Model](model: type[T], pk: int) -> T:
    row = model._default_manager.select_for_update().filter(pk=pk).first()
    if row is None:
        raise NotFound
    return row


def _store(lab_id: int, data: DocumentInput) -> Document:
    return Document.objects.create(
        lab_id=lab_id,
        content=data.content,
        content_type=document_type(data.content),
        size_bytes=len(data.content),
        sha256=hashlib.sha256(data.content).hexdigest(),
    )


def _contact_values(contact: ContactInput) -> dict[str, str]:
    return {"name": contact.name, "email": contact.email, "postal_address": contact.postal_address}


def _requester_values(data: RequesterInput) -> dict[str, Any]:
    return {
        "institution": data.institution,
        "legal_form": data.legal_form,
        "registration_number": data.registration_number,
        "seat": data.seat,
        "country": data.country,
        "lab_evidence": data.lab_evidence,
        "lab_confirmed_on": data.lab_confirmed_on.isoformat(),
    }


# Requesters.


def requester_create(*, access: Access, lab: Lab, data: RequesterInput) -> Requester:
    """An institution that may receive material, with its responsible scientist."""
    data = _checked_requester(data)
    with audited_atomic():
        locked_lab = lock_lab(lab.pk)
        _require(access, locked_lab.pk, Perm.MANAGE_DISTRIBUTION)
        person = Contact.objects.create(lab=locked_lab, **_contact_values(data.contact))
        values = _requester_values(data)
        requester = Requester.objects.create(
            lab=locked_lab,
            contact=person,
            **{**values, "lab_confirmed_on": data.lab_confirmed_on},
        )
        changed = {k: PERSONAL_CHANGED for k, v in _contact_values(data.contact).items() if v}
        record_event(
            REQUESTER_CREATED,
            Change(
                REQUESTER,
                requester.public_id,
                {
                    "contact": [None, str(person.public_id)],
                    **{k: [None, v] for k, v in values.items()},
                    **changed,
                },
                lab_id=locked_lab.pk,
            ),
        )
    return requester


def requester_update(*, access: Access, requester: Requester, data: RequesterInput) -> Requester:
    """Changes what differs; the same values again change nothing and record nothing. Requests
    already entered keep the destination they were entered with."""
    data = _checked_requester(data)
    with audited_atomic():
        lock_lab(requester.lab_id)
        _require(access, requester.lab_id, Perm.MANAGE_DISTRIBUTION)
        locked = _locked(Requester, requester.pk)
        person = _locked(Contact, locked.contact_id)
        if person.erased_at is not None:
            raise ContactErased
        changes: dict[str, Any] = {}
        for name, value in _contact_values(data.contact).items():
            if getattr(person, name) != value:
                setattr(person, name, value)
                changes[name] = PERSONAL_CHANGED
        if changes:
            person.save(update_fields=[*changes, "updated_at"])
        fields = []
        for name, value in _requester_values(data).items():
            stored = getattr(locked, name)
            old = stored.isoformat() if isinstance(stored, date) else stored
            if old != value:
                setattr(locked, name, getattr(data, name))
                changes[name] = [old, value]
                fields.append(name)
        if fields:
            locked.save(update_fields=[*fields, "updated_at"])
        if changes:
            record_event(
                REQUESTER_CHANGED,
                Change(REQUESTER, locked.public_id, changes, lab_id=locked.lab_id),
            )
    return locked


# Recipient permits.


def _checked_permit(data: PermitInput) -> PermitInput:
    issuer = normalised(data.issuer)
    reference = normalised(data.reference)
    covers = data.covers.strip()
    endorsement = normalised(data.endorsement_reference)
    if not issuer:
        raise InvalidDistribution("Enter the issuing authority.", attr="issuer")
    if data.issuer_country not in COUNTRY_CODES:
        raise InvalidDistribution("Choose a country.", attr="issuer_country")
    if not reference:
        raise InvalidDistribution("Enter the reference.", attr="reference")
    if data.expires_on is not None and data.expires_on < data.valid_from:
        raise InvalidDistribution("A permit expires after it starts.", attr="expires_on")
    if data.kind in NAMES_AGENTS and not covers:
        raise InvalidDistribution(
            "Write the agents or pests it names, as on the document.", attr="covers"
        )
    loa = data.kind == PermitKind.PLANT_HEALTH_LOA
    for name in ("quantity_allowed", "sendings_allowed"):
        value = getattr(data, name)
        if loa and (value is None or value < 1):
            raise InvalidDistribution("Enter a number of 1 or more.", attr=name)
        if not loa and value is not None:
            raise InvalidDistribution("Only a Letter of Authority states this.", attr=name)
    if (endorsement or data.endorsed_on) and not loa:
        raise InvalidDistribution(
            "Only a Letter of Authority is endorsed.", attr="endorsement_reference"
        )
    if bool(endorsement) != (data.endorsed_on is not None):
        attr = "endorsed_on" if endorsement else "endorsement_reference"
        raise InvalidDistribution("Give the endorsement with its day.", attr=attr)
    gmo = data.kind == PermitKind.GMO_CONTAINED_USE
    if gmo != (data.gmo_category is not None) or (gmo and not 1 <= (data.gmo_category or 0) <= 4):  # noqa: PLR2004
        raise InvalidDistribution(
            "A contained-use authorisation has a category 1 to 4, other permits none.",
            attr="gmo_category",
        )
    work = data.kind == PermitKind.PATHOGEN_WORK_PERMIT
    if work != (data.risk_group is not None) or (work and not 1 <= (data.risk_group or 0) <= 4):  # noqa: PLR2004
        raise InvalidDistribution(
            "A permit to work with pathogens has a risk group 1 to 4, other permits none.",
            attr="risk_group",
        )
    _checked_document(data.document)
    return PermitInput(
        kind=data.kind,
        issuer=issuer,
        issuer_country=data.issuer_country,
        reference=reference,
        valid_from=data.valid_from,
        document=data.document,
        expires_on=data.expires_on,
        covers=covers,
        quantity_allowed=data.quantity_allowed,
        sendings_allowed=data.sendings_allowed,
        endorsement_reference=endorsement,
        endorsed_on=data.endorsed_on,
        gmo_category=data.gmo_category,
        risk_group=data.risk_group,
    )


def permit_add(*, access: Access, requester: Requester, data: PermitInput) -> RecipientPermit:
    """A document the requester holds, with its file. Recorded once it is in hand."""
    data = _checked_permit(data)
    with audited_atomic():
        lock_lab(requester.lab_id)
        _require(access, requester.lab_id, Perm.MANAGE_DISTRIBUTION)
        locked = _locked(Requester, requester.pk)
        document = _store(locked.lab_id, data.document)
        permit = RecipientPermit.objects.create(
            lab_id=locked.lab_id,
            requester=locked,
            kind=data.kind,
            issuer=data.issuer,
            issuer_country=data.issuer_country,
            reference=data.reference,
            valid_from=data.valid_from,
            expires_on=data.expires_on,
            covers=data.covers,
            quantity_allowed=data.quantity_allowed,
            sendings_allowed=data.sendings_allowed,
            endorsement_reference=data.endorsement_reference,
            endorsed_on=data.endorsed_on,
            gmo_category=data.gmo_category,
            risk_group=data.risk_group,
            document=document,
        )
        values: dict[str, Any] = {
            "requester": str(locked.public_id),
            "kind": permit.kind,
            "issuer": permit.issuer,
            "issuer_country": permit.issuer_country,
            "reference": permit.reference,
            "valid_from": permit.valid_from.isoformat(),
            "expires_on": None if permit.expires_on is None else permit.expires_on.isoformat(),
            "covers": permit.covers,
            "quantity_allowed": permit.quantity_allowed,
            "sendings_allowed": permit.sendings_allowed,
            "endorsement_reference": permit.endorsement_reference,
            "endorsed_on": None if permit.endorsed_on is None else permit.endorsed_on.isoformat(),
            "gmo_category": permit.gmo_category,
            "risk_group": permit.risk_group,
            "document": {"public_id": str(document.public_id), "sha256": document.sha256},
        }
        record_event(
            RECIPIENT_PERMIT_ADDED,
            Change(
                PERMIT,
                permit.public_id,
                {k: [None, v] for k, v in values.items()},
                lab_id=locked.lab_id,
            ),
        )
    return permit


def permit_end(
    *, access: Access, permit: RecipientPermit, ended_on: date, reason: str
) -> RecipientPermit:
    """The permit stops holding from `ended_on` (revoked, surrendered, entered in error). The
    row stays; approvals already given keep the permit they were given against."""
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(permit.lab_id)
        _require(access, permit.lab_id, Perm.MANAGE_DISTRIBUTION)
        locked = _locked(RecipientPermit, permit.pk)
        if locked.ended_on is not None:
            raise PermitEnded
        if ended_on < locked.valid_from:
            raise InvalidDistribution(
                f"The permit starts on {locked.valid_from.isoformat()}: it ends on that day or"
                " later.",
                attr="ended_on",
            )
        locked.ended_on, locked.end_reason = ended_on, reason
        locked.save(update_fields=["ended_on", "end_reason", "updated_at"])
        record_event(
            RECIPIENT_PERMIT_ENDED,
            Change(
                PERMIT,
                locked.public_id,
                {"ended_on": [None, ended_on.isoformat()]},
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
    return locked


# Requests.


def _checked_request(data: NewRequest) -> NewRequest:
    end_use = data.end_use.strip()
    if not end_use:
        raise InvalidDistribution("Say what the recipient will use it for.", attr="end_use")
    if not 1 <= data.containment_level <= 4:  # noqa: PLR2004
        raise InvalidDistribution("A containment level is 1 to 4.", attr="containment_level")
    if not data.lines:
        raise InvalidDistribution("Add a strain.", attr="lines")
    if len(data.lines) > MAX_LINES:
        raise InvalidDistribution(f"A request has at most {MAX_LINES} strains.", attr="lines")
    seen: set[int] = set()
    for i, line in enumerate(data.lines):
        if line.strain.pk in seen:
            raise InvalidDistribution("This strain is listed twice.", attr=f"lines.{i}.strain")
        seen.add(line.strain.pk)
        if not 1 <= line.quantity <= MAX_VIALS_PER_LINE:
            raise InvalidDistribution(
                f"Ask for 1 to {MAX_VIALS_PER_LINE} vials.", attr=f"lines.{i}.quantity"
            )
    return NewRequest(
        requester=data.requester,
        use=data.use,
        end_use=end_use,
        containment_level=data.containment_level,
        lines=tuple(data.lines),
    )


def _next_number(lab: Lab, year: int) -> int:
    """The lab's next number in the year, from its counter row (caller holds the lab lock)."""
    counter = RequestCounter.objects.select_for_update().filter(lab=lab, year=year).first()
    if counter is None:
        counter = RequestCounter(lab=lab, year=year)
        _save(counter, {COUNTER_UNIQUE: NumberTaken()})
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return counter.last_number


def request_submit(*, access: Access, lab: Lab, data: NewRequest) -> DistributionRequest:
    """A request as the requester sent it, with its lines. Each line keeps the terms of the
    strain's deposit in force now and their MTA version. Refused outright when the requester's
    country is outside the EU."""
    data = _checked_request(data)
    with audited_atomic():
        locked_lab = lock_lab(lab.pk)
        _require(access, locked_lab.pk, Perm.MANAGE_DISTRIBUTION)
        requester = _locked(Requester, data.requester.pk)
        if requester.lab_id != locked_lab.pk:
            raise InvalidDistribution("Invalid requester.", attr="requester")
        if Contact.objects.filter(pk=requester.contact_id, erased_at__isnull=False).exists():
            raise InvalidDistribution("This requester's contact was erased.", attr="requester")
        strains = {
            s.pk: s
            for s in Strain.objects.select_for_update()
            .filter(pk__in=[line.strain.pk for line in data.lines], lab=locked_lab)
            .order_by("pk")
        }
        regulated = regulating_restrictions().filter(strain_id__in=strains).exists()
        refusal = policy.destination_finding(requester.country, regulated=regulated)
        if refusal is not None:
            raise DestinationRefused(refusal.sentence, code=refusal.code, attr="requester")
        terms = {
            t.deposit.strain_id: t
            for t in DepositTerms.objects.select_related("deposit", "mta").filter(
                deposit__strain_id__in=strains, is_active=True
            )
        }
        for i, line in enumerate(data.lines):
            if line.strain.pk not in strains:
                raise InvalidDistribution("Invalid strain.", attr=f"lines.{i}.strain")
            if line.strain.pk not in terms:
                raise InvalidDistribution(
                    "This strain has no terms: it came from no deposit.",
                    code="no_terms",
                    attr=f"lines.{i}.strain",
                )
        year = permit_today().year
        request = DistributionRequest(
            lab=locked_lab,
            year=year,
            number=_next_number(locked_lab, year),
            requester=requester,
            destination_country=requester.country,
            use=data.use,
            end_use=data.end_use,
            containment_level=data.containment_level,
            submitted_by=access.user,
        )
        _save(request, {REQUEST_NUMBER_UNIQUE: NumberTaken()})
        record_event(
            REQUEST_SUBMITTED,
            Change(
                REQUEST,
                request.public_id,
                {
                    "number": [None, request.label],
                    "requester": [None, str(requester.public_id)],
                    "destination_country": [None, request.destination_country],
                    "use": [None, request.use],
                    "end_use": [None, request.end_use],
                    "containment_level": [None, request.containment_level],
                    "status": [None, request.status],
                },
                lab_id=locked_lab.pk,
            ),
        )
        for line in data.lines:
            strain, pinned = strains[line.strain.pk], terms[line.strain.pk]
            row = RequestLine.objects.create(
                lab=locked_lab,
                request=request,
                strain=strain,
                quantity=line.quantity,
                terms=pinned,
                mta=pinned.mta,
            )
            mta = (
                None
                if pinned.mta is None
                else {
                    "public_id": str(pinned.mta.public_id),
                    "code": pinned.mta.code,
                    "version": pinned.mta.version,
                }
            )
            record_event(
                REQUEST_LINE_ADDED,
                Change(
                    LINE,
                    row.public_id,
                    {
                        "request": [None, str(request.public_id)],
                        "quantity": [None, row.quantity],
                        "terms": [
                            None,
                            {"version": pinned.version, "public_id": str(pinned.public_id)},
                        ],
                        "mta": [None, mta],
                    },
                    lab_id=locked_lab.pk,
                    strain_id=strain.public_id,
                ),
            )
    return request


def _locked_request(
    access: Access, request: DistributionRequest, perm: Perm
) -> DistributionRequest:
    lock_lab(request.lab_id)
    _require(access, request.lab_id, perm)
    return (
        DistributionRequest.objects.select_for_update(of=("self",))
        .select_related("requester__contact")
        .get(pk=request.pk)
    )


def acceptance_record(
    *, access: Access, request: DistributionRequest, data: AcceptanceInput
) -> MtaAcceptance:
    """The requester accepted an MTA version a line is pinned to, signed by `signer`. Recorded
    from the signed copy, which is kept as the evidence."""
    signer = _checked_contact(data.signer, "signer_", address=False)
    _checked_document(data.document)
    if data.accepted_on > permit_today():
        raise InvalidDistribution("This date is in the future.", attr="accepted_on")
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        if locked.status != RequestStatus.SUBMITTED:
            raise WrongState("An acceptance is recorded while the request waits for a decision.")
        line = (
            RequestLine.objects.select_related("mta")
            .filter(request=locked, mta_id=data.mta_id)
            .first()
        )
        if line is None or line.mta is None:
            raise InvalidDistribution("Choose an MTA version of this request.", attr="mta")
        person = Contact.objects.create(
            lab_id=locked.lab_id, name=signer.name, email=signer.email, postal_address=""
        )
        document = _store(locked.lab_id, data.document)
        acceptance = MtaAcceptance(
            lab_id=locked.lab_id,
            request=locked,
            mta=line.mta,
            signer=person,
            signer_role=data.signer_role,
            authorised_signatory=data.authorised_signatory,
            accepted_on=data.accepted_on,
            document=document,
        )
        _save(acceptance, {ACCEPTANCE_UNIQUE: AcceptanceExists()})
        record_event(
            MTA_ACCEPTANCE_RECORDED,
            Change(
                ACCEPTANCE,
                acceptance.public_id,
                {
                    "request": [None, str(locked.public_id)],
                    "mta": [None, {"code": line.mta.code, "version": line.mta.version}],
                    "signer": PERSONAL_CHANGED,
                    "signer_role": [None, acceptance.signer_role],
                    "authorised_signatory": [None, acceptance.authorised_signatory],
                    "accepted_on": [None, acceptance.accepted_on.isoformat()],
                    "document": [
                        None,
                        {"public_id": str(document.public_id), "sha256": document.sha256},
                    ],
                },
                lab_id=locked.lab_id,
            ),
        )
    return acceptance


def _defer_reservation_checks(*, shipment: bool = False) -> None:
    """A vial and its reservation change one after the other, and a shipment is written before
    its vials: the triggers that hold them together check at commit, also in a session that
    set its constraints immediate."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SET CONSTRAINTS distribution_vial_reserved_by_request,"
            " distribution_reservation_holds_vial"
            + (
                ", distribution_shipment_complete, distribution_shipment_documented"
                if shipment
                else ""
            )
            + " DEFERRED"
        )


def _move(
    locked: DistributionRequest, status: RequestStatus, *, source: RequestStatus | None = None
) -> RequestStatus:
    """The one edge check. `source` names the one status the action starts from, where two
    statuses lead to the same one (approved, and back from awaiting confirmation; shipped in one
    step, and confirmed)."""
    old = RequestStatus(locked.status)
    if status not in REQUEST_EDGES[old] or source not in (None, old):
        raise WrongState(f"A {old.label.lower()} request cannot be {status.label.lower()}.")
    return old


def request_approve(
    *, access: Access, request: DistributionRequest, reason: str = ""
) -> DistributionRequest:
    """Curators approve; a manager approves when a finding asks for one, with a reason. Every
    blocker refuses. The vials are reserved now (D19, no expiry): for each line, the available
    vials of distributable batches of its strain, locked in pk order and skipping those another
    approval holds, all chosen before anything is written."""
    reason = reason.strip()
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.APPROVED, source=RequestStatus.SUBMITTED)
        lines = list(locked.lines.select_related("strain").order_by("pk"))
        # The strains next (lock order lab, request, strain, vial): their status and
        # restrictions change only under the lab lock, the lock here keeps the order explicit.
        list(
            Strain.objects.select_for_update()
            .filter(pk__in=[line.strain_id for line in lines])
            .order_by("pk")
        )
        evaluation = policy.evaluate(locked, permit_today())
        blockers = evaluation.blockers
        if blockers:
            raise RequestBlocked(" ".join(f.sentence for f in blockers))
        if evaluation.needs_manager:
            try:
                _require(access, locked.lab_id, Perm.APPROVE_REGULATED)
            except Forbidden:
                raise ManagerRequired from None
            if not reason:
                raise RuleViolation(
                    "Say why the findings allow it.", code="reason_required", attr="reason"
                )
        chosen: dict[int, list[Vial]] = {}
        for line in lines:
            vials = list(
                Vial.objects.select_for_update(skip_locked=True, of=("self",))
                .filter(
                    distributable("batch__"),
                    lab_id=locked.lab_id,
                    status=VialStatus.AVAILABLE,
                    batch__strain_id=line.strain_id,
                )
                .select_related("batch__strain")
                .order_by("pk")[: line.quantity]
            )
            if len(vials) < line.quantity:
                raise NotEnoughVials(
                    f"{line.strain.accession_number}: {len(vials)} vials are free now, the line"
                    f" asks for {line.quantity}."
                )
            chosen[line.pk] = vials
        now = timezone.now()
        label = f"Reserved for request {locked.label}."
        _defer_reservation_checks()
        for line in lines:
            for vial in chosen[line.pk]:
                lineage.vial_reserve_locked(access=access, vial=vial, reason=label)
                _save(
                    VialReservation(
                        lab_id=locked.lab_id,
                        line=line,
                        vial=vial,
                        reserved_at=now,
                        reserved_by=access.user,
                    ),
                    {ONE_OPEN_RESERVATION: ReservedMeanwhile()},
                )
            permits = {p.pk: p for ln, p in evaluation.used if ln.pk == line.pk}
            for permit in permits.values():
                LinePermit.objects.create(line=line, permit=permit)
            record_event(
                REQUEST_LINE_RESERVED,
                Change(
                    LINE,
                    line.public_id,
                    {
                        "vials": [None, [str(v.public_id) for v in chosen[line.pk]]],
                        "permits": [None, sorted(str(p.public_id) for p in permits.values())],
                    },
                    lab_id=locked.lab_id,
                    strain_id=line.strain.public_id,
                ),
            )
        locked.status, locked.decided_by, locked.decided_at = (
            RequestStatus.APPROVED,
            access.user,
            now,
        )
        locked.decision_reason = reason
        locked.save(
            update_fields=["status", "decided_by", "decided_at", "decision_reason", "updated_at"]
        )
        record_event(
            REQUEST_APPROVED,
            Change(
                REQUEST,
                locked.public_id,
                {
                    "status": [old, RequestStatus.APPROVED],
                    "findings": [None, [f.code for f in evaluation.findings]],
                },
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
    return locked


def request_reject(
    *, access: Access, request: DistributionRequest, reason: str
) -> DistributionRequest:
    """The request is refused, with the reason: kept for good (OECD 11.5), nothing reserved."""
    reason = _check_reason(reason)
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.REJECTED)
        locked.status, locked.decided_by, locked.decided_at = (
            RequestStatus.REJECTED,
            access.user,
            timezone.now(),
        )
        locked.decision_reason = reason
        locked.save(
            update_fields=["status", "decided_by", "decided_at", "decision_reason", "updated_at"]
        )
        record_event(
            REQUEST_REJECTED,
            Change(
                REQUEST,
                locked.public_id,
                {"status": [old, RequestStatus.REJECTED]},
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
    return locked


def request_cancel(
    *, access: Access, request: DistributionRequest, reason: str
) -> DistributionRequest:
    """The request is withdrawn, before or after approval. Its open reservations end and their
    vials are available again."""
    reason = _check_reason(reason)
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.CANCELLED)
        lines = list(locked.lines.select_related("strain").order_by("pk"))
        list(
            Strain.objects.select_for_update()
            .filter(pk__in=[line.strain_id for line in lines])
            .order_by("pk")
        )
        now = timezone.now()
        _defer_reservation_checks()
        open_rows = list(
            # of=self: a join locks every table it reads, and lines take no UPDATE (frozen).
            VialReservation.objects.select_for_update(of=("self",))
            .filter(line__request=locked, ended_at__isnull=True)
            .order_by("vial_id")
        )
        vials = {
            v.pk: v
            for v in Vial.objects.select_for_update(of=("self",))
            .select_related("batch__strain")
            .filter(pk__in=[r.vial_id for r in open_rows])
            .order_by("pk")
        }
        for line in lines:
            reservations = [r for r in open_rows if r.line_id == line.pk]
            if not reservations:
                continue
            for reservation in reservations:
                reservation.ended_at, reservation.ended_by = now, access.user
                reservation.end_reason = ReservationEnd.CANCELLED
                reservation.save(update_fields=["ended_at", "ended_by", "end_reason", "updated_at"])
                lineage.vial_release_locked(
                    access=access,
                    vial=vials[reservation.vial_id],
                    reason=f"Request {locked.label} was cancelled.",
                )
            record_event(
                REQUEST_LINE_RELEASED,
                Change(
                    LINE,
                    line.public_id,
                    {"vials": [[str(vials[r.vial_id].public_id) for r in reservations], None]},
                    lab_id=locked.lab_id,
                    strain_id=line.strain.public_id,
                ),
                reason=reason,
            )
        locked.status, locked.cancelled_by, locked.cancelled_at = (
            RequestStatus.CANCELLED,
            access.user,
            now,
        )
        locked.cancel_reason = reason
        locked.save(
            update_fields=["status", "cancelled_by", "cancelled_at", "cancel_reason", "updated_at"]
        )
        record_event(
            REQUEST_CANCELLED,
            Change(
                REQUEST,
                locked.public_id,
                {"status": [old, RequestStatus.CANCELLED]},
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
    return locked


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


# The two-person shipment of a regulated request (#89, ADR 0009).


def _open_preparation(locked: DistributionRequest) -> ShipmentPreparation:
    """The request's one preparation not withdrawn (a partial unique index). The request's lock
    serialises every writer of it, so it takes no lock of its own."""
    return ShipmentPreparation.objects.select_related("responsible", "prepared_by").get(
        request=locked, withdrawn_at__isnull=True
    )


def request_prepare_shipment(
    *, access: Access, request: DistributionRequest, data: ShipmentInput
) -> DistributionRequest:
    """Step 1 for a request with a regulated line: the shipment as this person records it, the
    same facts as a shipment in one step. The gates run today; the request awaits a second
    person's confirmation. Nothing leaves: the vials stay reserved."""
    data = _checked_shipment(data)
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.AWAITING_CONFIRMATION, source=RequestStatus.APPROVED)
        _, strains = _locked_strains(locked)
        _gates_today(locked)
        if not _regulated(strains):
            raise ShipInOneStep
        _check_exempt(data.classification_basis, strains)
        preparation = ShipmentPreparation(
            **_package(data, locked.lab_id),
            request=locked,
            prepared_by=access.user,
            prepared_at=timezone.now(),
        )
        _save(preparation, {ONE_OPEN_PREPARATION: PreparedMeanwhile()})
        locked.status = RequestStatus.AWAITING_CONFIRMATION
        locked.save(update_fields=["status", "updated_at"])
        record_event(
            REQUEST_SHIPMENT_PREPARED,
            Change(
                REQUEST,
                locked.public_id,
                {
                    "status": [old, RequestStatus.AWAITING_CONFIRMATION],
                    "preparation": [None, str(preparation.public_id)],
                    **_package_changes(preparation),
                },
                lab_id=locked.lab_id,
            ),
        )
    return locked


def request_confirm_shipment(
    *, access: Access, request: DistributionRequest, preparation: uuid.UUID
) -> DistributionRequest:
    """Step 2: a different person confirms the prepared shipment they read (`preparation`, its
    public id): neither the approver nor the preparer. The gates run again today, then exactly
    what a shipment in one step does happens, with the preparation's facts. The event holds
    both people and both times (ADR 0009)."""
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.SHIPPED, source=RequestStatus.AWAITING_CONFIRMATION)
        prepared = _open_preparation(locked)
        if prepared.public_id != preparation:
            raise PreparationChanged
        if locked.decided_by_id == access.user.pk:
            raise ConfirmOwnApproval
        if prepared.prepared_by_id == access.user.pk:
            raise ConfirmOwnPreparation
        lines, strains = _locked_strains(locked)
        today = _gates_today(locked)
        _check_exempt(prepared.classification_basis, strains)
        now = timezone.now()
        _defer_reservation_checks(shipment=True)
        shipment = Shipment.objects.create(
            **{f: getattr(prepared, f) for f in PACKAGE_FIELDS},
            lab_id=locked.lab_id,
            request=locked,
            preparation=prepared,
            classified_by_id=prepared.prepared_by_id,
            classified_at=prepared.prepared_at,
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
                    "preparation": [None, str(prepared.public_id)],
                    # Pseudonymous: public ids, never names (ADR 0005).
                    "prepared_by": [None, str(prepared.prepared_by.public_id)],
                    "prepared_at": [None, prepared.prepared_at.isoformat()],
                    "confirmed_by": [None, str(access.user.public_id)],
                    "confirmed_at": [None, now.isoformat()],
                },
                lab_id=locked.lab_id,
            ),
        )
        _write_documents(locked, shipment, today)
        _exhaust_emptied(locked, batches)
    return locked


def request_withdraw_shipment(
    *, access: Access, request: DistributionRequest, reason: str
) -> DistributionRequest:
    """The prepared shipment is withdrawn, with the reason, by its preparer or anyone else who
    manages distribution: the request is approved again and may be prepared anew. The
    preparation stays as history, its facts unchanged."""
    reason = _check_reason(reason)
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        old = _move(locked, RequestStatus.APPROVED, source=RequestStatus.AWAITING_CONFIRMATION)
        prepared = _open_preparation(locked)
        prepared.withdrawn_by, prepared.withdrawn_at = access.user, timezone.now()
        prepared.withdraw_reason = reason
        prepared.save(
            update_fields=["withdrawn_by", "withdrawn_at", "withdraw_reason", "updated_at"]
        )
        locked.status = RequestStatus.APPROVED
        locked.save(update_fields=["status", "updated_at"])
        record_event(
            REQUEST_SHIPMENT_WITHDRAWN,
            Change(
                REQUEST,
                locked.public_id,
                {
                    "status": [old, RequestStatus.APPROVED],
                    "preparation": [str(prepared.public_id), None],
                },
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
    return locked

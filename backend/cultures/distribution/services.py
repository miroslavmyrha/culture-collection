"""Every write of distribution (#18, part A): requesters and their permits, requests with their
lines, MTA acceptances, and the decisions on a request with the vials reserved at approval.

Each service runs in audited_atomic() and records its events in the same transaction. Lock
order, as everywhere: the lab row first (labs.locks.lock_lab), then the request, then the
strains of its lines by pk, then the vials (lineage keeps lab, strain, batch, vial, box; a
request sits between the lab and its strains). Under the lab lock each service re-reads the
actor's role, so a member demoted after the request built its access object is refused. A
refusal raises before anything is written, or rolls back what was, so it changes nothing and
records nothing.

Personal data (D11): the responsible scientist and an MTA's signer are contacts; events record
their fields as "changed", never the value. Events about a line or its vials carry the strain
(D13); a request spans strains, so its own events carry none and each line has its own.
"""

import hashlib
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
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
    REQUEST_REJECTED,
    REQUEST_SUBMITTED,
    REQUESTER_CHANGED,
    REQUESTER_CREATED,
)
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import Conflict, DomainError, Forbidden, NotFound, RuleViolation
from cultures.deposits.models import Contact, DepositTerms, Use
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Perm, Role, role_has
from cultures.lineage import services as lineage
from cultures.lineage.models import Vial, VialStatus
from cultures.lineage.selectors import distributable
from cultures.strains.countries import COUNTRY_CODES
from cultures.strains.models import Strain
from cultures.strains.selectors import regulating_restrictions

from . import policy
from .models import (
    ACCEPTANCE_UNIQUE,
    COUNTER_UNIQUE,
    MAX_DOCUMENT_BYTES,
    MAX_VIALS_PER_LINE,
    NAMES_AGENTS,
    ONE_OPEN_RESERVATION,
    REQUEST_EDGES,
    REQUEST_NUMBER_UNIQUE,
    DistributionRequest,
    Document,
    DocumentType,
    LegalForm,
    LinePermit,
    MtaAcceptance,
    PermitKind,
    RecipientPermit,
    RequestCounter,
    Requester,
    RequestLine,
    RequestStatus,
    ReservationEnd,
    SignerRole,
    VialReservation,
)

REQUESTER, CONTACT, PERMIT, REQUEST, LINE, ACCEPTANCE = (
    "requester",
    "contact",
    "recipient_permit",
    "distribution_request",
    "request_line",
    "mta_acceptance",
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


@dataclass(frozen=True)
class ContactInput:
    name: str
    email: str = ""
    postal_address: str = ""


@dataclass(frozen=True)
class RequesterInput:
    contact: ContactInput  # the responsible scientist; the postal address is the delivery address
    institution: str
    legal_form: LegalForm
    country: str
    lab_evidence: str
    lab_confirmed_on: date
    registration_number: str = ""


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


def _defer_reservation_checks() -> None:
    """A vial and its reservation change one after the other: the triggers that hold them
    together check at commit, also in a session that set its constraints immediate."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SET CONSTRAINTS distribution_vial_reserved_by_request,"
            " distribution_reservation_holds_vial DEFERRED"
        )


def _move(locked: DistributionRequest, status: RequestStatus) -> RequestStatus:
    old = RequestStatus(locked.status)
    if status not in REQUEST_EDGES[old]:
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
        old = _move(locked, RequestStatus.APPROVED)
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

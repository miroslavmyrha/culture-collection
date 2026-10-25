"""Shared by the distribution services: entity names, input checks, locks, the edge check."""

import hashlib
import unicodedata

from django.db import IntegrityError, connection, transaction
from django.db.models import Model

from cultures.core.exceptions import DomainError, Forbidden, NotFound, RuleViolation
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Membership
from cultures.labs.permissions import Perm, Role, role_has

from ..models import (
    MAX_DOCUMENT_BYTES,
    REQUEST_EDGES,
    DistributionRequest,
    Document,
    DocumentType,
    RequestStatus,
)
from .errors import (
    InvalidDistribution,
    WrongState,
)
from .inputs import (
    ContactInput,
    DocumentInput,
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


# The first bytes of each document type (the files' own signatures, never the name or header).
SIGNATURES: tuple[tuple[bytes, DocumentType], ...] = (
    (b"%PDF-", DocumentType.PDF),
    (b"\x89PNG\r\n\x1a\n", DocumentType.PNG),
    (b"\xff\xd8\xff", DocumentType.JPEG),
)


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

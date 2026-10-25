"""Requesters and their recipient permits."""

from datetime import date
from typing import Any

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    PERSONAL_CHANGED,
    RECIPIENT_PERMIT_ADDED,
    RECIPIENT_PERMIT_ENDED,
    REQUESTER_CHANGED,
    REQUESTER_CREATED,
)
from cultures.biosafety.policy import permit_today
from cultures.deposits.models import Contact
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.strains.countries import COUNTRY_CODES

from ..models import (
    NAMES_AGENTS,
    PermitKind,
    RecipientPermit,
    Requester,
)
from ._shared import (
    PERMIT,
    REQUESTER,
    _check_reason,
    _checked_contact,
    _checked_document,
    _contact_values,
    _locked,
    _require,
    _store,
    normalised,
)
from .errors import (
    ContactErased,
    InvalidDistribution,
    PermitEnded,
)
from .inputs import (
    PermitInput,
    RequesterInput,
)


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

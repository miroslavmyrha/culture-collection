"""Every write on depositors, MTA templates, deposits and their terms (ADR 0008, #10, #12).

Each service runs in audited_atomic() and records its events in the same
transaction. Lock order, as in strains.services: the lab row first
(labs.locks.lock_lab), then the rows of that lab. Under the lab lock each
service re-reads the actor's role, so a curator demoted after the request built
its access object is refused.

Contacts (D11) hold the personal data. Events record their fields as
"changed", never the value (audit.registry.PERSONAL_FIELDS).

Intake (D8): deposit_receive records the receipt with terms version 1,
deposit_start_check moves it to checking, and deposit_accept or deposit_reject
decides it. Acceptance creates the strain through strains.services.strain_create
(numbered, with the biosafety gates of #11) and its passage 0 from the deposit
(D3); a rejection burns no number. Every refusal raises before anything is
written, or rolls back what was, so it changes nothing and records nothing.
"""

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Max, Model
from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    CONTACT_ERASED,
    DEPOSIT_ACCEPTED,
    DEPOSIT_CHECK_STARTED,
    DEPOSIT_RECEIVED,
    DEPOSIT_REJECTED,
    DEPOSIT_TERMS_REPLACED,
    DEPOSITOR_CHANGED,
    DEPOSITOR_CREATED,
    MTA_TEMPLATE_PUBLISHED,
    PASSAGE_CREATED,
    PERSONAL_CHANGED,
)
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import Conflict, DomainError, Forbidden, NotFound, RuleViolation
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Perm, Role, role_has
from cultures.lineage.models import Passage
from cultures.strains import services as strains
from cultures.strains.countries import COUNTRY_CODES
from cultures.strains.models import Pathogenicity
from cultures.strains.services import normalised
from cultures.taxonomy.models import Taxon

from .models import (
    MTA_CODE,
    MTA_VERSION_UNIQUE,
    ONE_ACTIVE_TERMS,
    TERMS_VERSION_UNIQUE,
    AbsScope,
    Condition,
    Contact,
    Decision,
    Deposit,
    Depositor,
    DepositStatus,
    DepositTerms,
    MtaTemplate,
    TermsUse,
    Use,
)

DEPOSITOR, CONTACT, DEPOSIT, MTA, PASSAGE = (
    "depositor",
    "contact",
    "deposit",
    "mta_template",
    "passage",
)
MAX_MTA_TEXT = 100_000


class InvalidDeposit(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class ContactErased(Conflict):
    default_code = "contact_erased"
    default_detail = "This depositor's contact was erased."


class WrongState(Conflict):
    """The deposit is not in the state the action starts from: someone acted first."""

    default_code = "deposit_state"
    default_detail = "The deposit is no longer in this state. Reload it."


class TermsChanged(Conflict):
    default_code = "terms_changed"
    default_detail = "The terms changed at the same moment. Reload them."


class MtaVersionTaken(Conflict):
    default_code = "mta_version_taken"
    default_detail = "Another version of this MTA was published at the same moment. Try again."


@dataclass(frozen=True)
class ContactInput:
    name: str
    email: str = ""
    postal_address: str = ""


@dataclass(frozen=True)
class TermsInput:
    abs_scope: AbsScope
    uses: Sequence[tuple[Use, Decision]]
    mta: MtaTemplate | None = None
    country_of_origin: str = ""
    collection_date: str = ""
    pic_reference: str = ""
    mat_reference: str = ""
    ircc: str = ""
    permit_reference: str = ""
    # The uses by a subsequent user the MAT covers: in scope only.
    mat_uses: Sequence[Use] = ()


@dataclass(frozen=True)
class NewDeposit:
    depositor: Depositor
    received_on: date
    condition: Condition
    name_as_received: str
    terms: TermsInput
    condition_note: str = ""
    depositor_passages: int | None = None


@dataclass(frozen=True)
class StrainFacts:
    """What the check found: everything a strain needs but the name, which the deposit has."""

    taxon: Taxon
    identified_on: date
    identification_method: str
    risk_group: int
    animal_pathogenicity: Pathogenicity = Pathogenicity.UNKNOWN
    plant_pathogenicity: Pathogenicity = Pathogenicity.UNKNOWN
    isolation_source: str = ""
    country_of_origin: str = ""
    isolation_date: str = ""
    restrictions: Sequence[strains.RestrictionInput] = field(default_factory=tuple)


# Checks on the input alone: no query, so they run before any lock.


def _checked_contact(contact: ContactInput) -> ContactInput:
    name = normalised(contact.name)
    if not name:
        raise InvalidDeposit("Enter the name.", attr="name")
    email = contact.email.strip()
    if email and (email.count("@") != 1 or any(c.isspace() for c in email)):
        raise InvalidDeposit("Enter an e-mail address.", attr="email")
    lines = [" ".join(line.split()) for line in contact.postal_address.splitlines()]
    address = "\n".join(line for line in lines if line)
    return ContactInput(name, email, unicodedata.normalize("NFC", address))


def _checked_terms(terms: TermsInput, prefix: str = "terms.") -> TermsInput:
    values = {
        name: normalised(getattr(terms, name))
        for name in ("pic_reference", "mat_reference", "ircc", "permit_reference")
    }
    if terms.country_of_origin and terms.country_of_origin not in COUNTRY_CODES:
        raise InvalidDeposit("Choose a country.", attr=f"{prefix}country_of_origin")
    try:
        strains.check_partial_date(terms.collection_date, f"{prefix}collection_date")
    except strains.InvalidStrain as error:
        raise InvalidDeposit(error.detail, attr=error.attr) from None
    # 511/2014, Art. 4(3)(a): in scope means the certificate of compliance, or the permit.
    if terms.abs_scope == AbsScope.IN_SCOPE and not (values["ircc"] or values["permit_reference"]):
        raise InvalidDeposit(
            "Material in scope of the ABS regulation needs an IRCC or a permit reference.",
            attr=f"{prefix}ircc",
        )
    mat = set(terms.mat_uses)
    if mat and terms.abs_scope != AbsScope.IN_SCOPE:
        raise InvalidDeposit(
            "Only material in scope of the ABS regulation has mutually agreed terms to cover uses.",
            attr=f"{prefix}mat_uses",
        )
    seen: set[str] = set()
    for i, (use, _) in enumerate(terms.uses):
        if use in seen:
            raise InvalidDeposit("This use is listed twice.", attr=f"{prefix}uses.{i}.use")
        seen.add(use)
    missing = [Use(use).label for use in Use.values if use not in seen]
    if missing:
        raise InvalidDeposit(
            f"Decide every use. Missing: {', '.join(missing)}.", attr=f"{prefix}uses"
        )
    return TermsInput(
        abs_scope=terms.abs_scope,
        uses=tuple(terms.uses),
        # One order, the vocabulary's, so equal sets are equal lists in the row and the event.
        mat_uses=tuple(Use(use) for use in Use.values if use in mat),
        mta=terms.mta,
        country_of_origin=terms.country_of_origin,
        collection_date=terms.collection_date,
        **values,
    )


def _check_reason(reason: str) -> str:
    if not reason.strip():
        raise RuleViolation("A reason is required.", code="reason_required", attr="reason")
    return reason.strip()


def mta_text(text: str) -> str:
    """The text as stored and hashed: NFC, Unix line ends, no space at either end."""
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def _contact_values(contact: ContactInput) -> dict[str, str]:
    return {"name": contact.name, "email": contact.email, "postal_address": contact.postal_address}


# Depositors and their contacts.


def depositor_create(
    *, access: Access, lab: Lab, contact: ContactInput, institution: str = ""
) -> Depositor:
    contact = _checked_contact(contact)
    institution = normalised(institution)
    with audited_atomic():
        locked_lab = lock_lab(lab.pk)
        _require(access, locked_lab.pk, Perm.MANAGE_DEPOSITS)
        person = Contact.objects.create(lab=locked_lab, **_contact_values(contact))
        depositor = Depositor.objects.create(
            lab=locked_lab, contact=person, institution=institution
        )
        changed = {k: PERSONAL_CHANGED for k, v in _contact_values(contact).items() if v}
        record_event(
            DEPOSITOR_CREATED,
            Change(
                DEPOSITOR,
                depositor.public_id,
                {
                    "contact": [None, str(person.public_id)],
                    "institution": [None, institution],
                    **changed,
                },
                lab_id=locked_lab.pk,
            ),
        )
    return depositor


def depositor_update(
    *, access: Access, depositor: Depositor, contact: ContactInput, institution: str = ""
) -> Depositor:
    """Changes what differs; the same values again change nothing and record nothing."""
    contact = _checked_contact(contact)
    institution = normalised(institution)
    with audited_atomic():
        lock_lab(depositor.lab_id)
        _require(access, depositor.lab_id, Perm.MANAGE_DEPOSITS)
        locked = _locked(Depositor, depositor.pk)
        person = _locked(Contact, locked.contact_id)
        if person.erased_at is not None:
            raise ContactErased
        changes: dict[str, Any] = {}
        for name, value in _contact_values(contact).items():
            if getattr(person, name) != value:
                setattr(person, name, value)
                changes[name] = PERSONAL_CHANGED
        if changes:
            person.save(update_fields=[*changes, "updated_at"])
        if locked.institution != institution:
            changes["institution"] = [locked.institution, institution]
            locked.institution = institution
            locked.save(update_fields=["institution", "updated_at"])
        if changes:
            record_event(
                DEPOSITOR_CHANGED,
                Change(DEPOSITOR, locked.public_id, changes, lab_id=locked.lab_id),
            )
    return locked


def contact_erase(*, contact: Contact, reason: str) -> Contact:
    """An erasure request (ADR 0005, #37): the person's values go, the row stays for the
    depositor and its deposits. For staff, through the erase_contact command. A second
    erasure changes nothing and records nothing."""
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(contact.lab_id)
        locked = _locked(Contact, contact.pk)
        if locked.erased_at is not None:
            return locked
        values = {**_contact_values(_as_input(locked)), "phone": locked.phone}
        changed = [name for name, value in values.items() if value]
        locked.name, locked.email, locked.postal_address, locked.phone = "", "", "", ""
        locked.erased_at = timezone.now()
        locked.save(
            update_fields=["name", "email", "postal_address", "phone", "erased_at", "updated_at"]
        )
        record_event(
            CONTACT_ERASED,
            Change(
                CONTACT,
                locked.public_id,
                dict.fromkeys(changed, PERSONAL_CHANGED),
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
    return locked


def _as_input(contact: Contact) -> ContactInput:
    return ContactInput(contact.name, contact.email, contact.postal_address)


# MTA templates.


def mta_template_publish(
    *, access: Access, lab: Lab, code: str, title: str, text: str
) -> MtaTemplate:
    """The next version of the lab's MTA with this code (1 for a new code). Frozen once stored."""
    code = code.strip().upper()
    if not re.fullmatch(MTA_CODE, code):
        raise InvalidDeposit(
            "Use up to 20 capital letters, digits and hyphens, for example STD.", attr="code"
        )
    title = normalised(title)
    if not title:
        raise InvalidDeposit("Enter the title.", attr="title")
    text = mta_text(text)
    if not text:
        raise InvalidDeposit("Enter the text of the agreement.", attr="text")
    if len(text) > MAX_MTA_TEXT:
        raise InvalidDeposit(f"Use at most {MAX_MTA_TEXT} characters.", attr="text")
    with audited_atomic():
        locked_lab = lock_lab(lab.pk)
        _require(access, locked_lab.pk, Perm.MANAGE_MTA)
        last = MtaTemplate.objects.filter(lab=locked_lab, code=code).aggregate(v=Max("version"))
        template = MtaTemplate(
            lab=locked_lab,
            code=code,
            version=(last["v"] or 0) + 1,
            title=title,
            text=text,
            text_sha256=sha256_of(text),
        )
        _save(template, {MTA_VERSION_UNIQUE: MtaVersionTaken()})
        record_event(
            MTA_TEMPLATE_PUBLISHED,
            Change(
                MTA,
                template.public_id,
                {
                    "code": [None, code],
                    "version": [None, template.version],
                    "title": [None, title],
                    "text_sha256": [None, template.text_sha256],
                },
                lab_id=locked_lab.pk,
            ),
        )
    return template


# Deposits.


def _terms_values(terms: TermsInput) -> dict[str, Any]:
    return {
        "mta": str(terms.mta.public_id) if terms.mta else None,
        "abs_scope": terms.abs_scope,
        "country_of_origin": terms.country_of_origin,
        "collection_date": terms.collection_date,
        "pic_reference": terms.pic_reference,
        "mat_reference": terms.mat_reference,
        "ircc": terms.ircc,
        "permit_reference": terms.permit_reference,
        "mat_uses": list(terms.mat_uses),
        "uses": dict(terms.uses),
    }


def _add_terms(deposit: Deposit, terms: TermsInput, version: int, reason: str) -> DepositTerms:
    if terms.mta is not None and terms.mta.lab_id != deposit.lab_id:
        raise InvalidDeposit("Invalid MTA template.", attr="terms.mta")
    row = DepositTerms(
        lab_id=deposit.lab_id,
        deposit=deposit,
        version=version,
        is_active=True,
        mta=terms.mta,
        abs_scope=terms.abs_scope,
        country_of_origin=terms.country_of_origin,
        collection_date=terms.collection_date,
        pic_reference=terms.pic_reference,
        mat_reference=terms.mat_reference,
        ircc=terms.ircc,
        permit_reference=terms.permit_reference,
        mat_uses=list(terms.mat_uses),
        reason=reason,
    )
    _save(row, {TERMS_VERSION_UNIQUE: TermsChanged(), ONE_ACTIVE_TERMS: TermsChanged()})
    TermsUse.objects.bulk_create(
        TermsUse(terms=row, use=use, decision=decision) for use, decision in terms.uses
    )
    return row


def deposit_receive(*, access: Access, lab: Lab, data: NewDeposit) -> Deposit:
    """The material arrived: the deposit is received, with its terms as version 1."""
    name = normalised(data.name_as_received)
    if not name:
        raise InvalidDeposit("Enter the name as received.", attr="name_as_received")
    if data.received_on > permit_today():
        raise InvalidDeposit("This date is in the future.", attr="received_on")
    note = data.condition_note.strip()
    if data.condition != Condition.INTACT and not note:
        raise InvalidDeposit("Say what was wrong with it.", attr="condition_note")
    terms = _checked_terms(data.terms)
    with audited_atomic():
        locked_lab = lock_lab(lab.pk)
        _require(access, locked_lab.pk, Perm.MANAGE_DEPOSITS)
        depositor = _locked(Depositor, data.depositor.pk)
        if depositor.lab_id != locked_lab.pk:
            raise InvalidDeposit("Invalid depositor.", attr="depositor")
        if Contact.objects.filter(pk=depositor.contact_id, erased_at__isnull=False).exists():
            raise InvalidDeposit("This depositor's contact was erased.", attr="depositor")
        deposit = Deposit.objects.create(
            lab=locked_lab,
            depositor=depositor,
            status=DepositStatus.RECEIVED,
            received_on=data.received_on,
            condition=data.condition,
            condition_note=note,
            name_as_received=name,
            depositor_passages=data.depositor_passages,
        )
        added = _add_terms(deposit, terms, version=1, reason="")
        record_event(
            DEPOSIT_RECEIVED,
            Change(
                DEPOSIT,
                deposit.public_id,
                {
                    "status": [None, deposit.status],
                    "depositor": [None, str(depositor.public_id)],
                    "received_on": [None, data.received_on.isoformat()],
                    "condition": [None, deposit.condition],
                    "condition_note": [None, note],
                    "name_as_received": [None, name],
                    "depositor_passages": [None, data.depositor_passages],
                    "terms": [
                        None,
                        {"version": 1, "public_id": str(added.public_id), **_terms_values(terms)},
                    ],
                },
                lab_id=locked_lab.pk,
            ),
        )
    return deposit


def _strain_id(deposit: Deposit) -> Any:
    return deposit.strain.public_id if deposit.strain is not None else None


def deposit_terms_replace(
    *, access: Access, deposit: Deposit, terms: TermsInput, reason: str
) -> DepositTerms:
    """A new version becomes the active one; the old one stays as it was. Allowed until the
    deposit is rejected: the terms follow the material after acceptance too."""
    terms = _checked_terms(terms)
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(deposit.lab_id)
        _require(access, deposit.lab_id, Perm.MANAGE_DEPOSITS)
        locked = (
            Deposit.objects.select_for_update(of=("self",))
            .select_related("strain")
            .filter(pk=deposit.pk)
            .first()
        )
        if locked is None:
            raise NotFound
        if locked.status == DepositStatus.REJECTED:
            raise WrongState("A rejected deposit keeps its terms.")
        current = DepositTerms.objects.select_for_update().get(deposit=locked, is_active=True)
        current.is_active = False
        current.save(update_fields=["is_active", "updated_at"])
        added = _add_terms(locked, terms, version=current.version + 1, reason=reason)
        record_event(
            DEPOSIT_TERMS_REPLACED,
            Change(
                DEPOSIT,
                locked.public_id,
                {
                    "terms": [
                        {"version": current.version, "public_id": str(current.public_id)},
                        {
                            "version": added.version,
                            "public_id": str(added.public_id),
                            **_terms_values(terms),
                        },
                    ]
                },
                lab_id=locked.lab_id,
                strain_id=_strain_id(locked),
            ),
            reason=reason,
        )
    return added


def _locked_deposit(access: Access, deposit: Deposit, expected: DepositStatus) -> Deposit:
    lock_lab(deposit.lab_id)
    _require(access, deposit.lab_id, Perm.MANAGE_DEPOSITS)
    locked = _locked(Deposit, deposit.pk)
    if locked.status != expected:
        raise WrongState
    return locked


def deposit_start_check(*, access: Access, deposit: Deposit) -> Deposit:
    with audited_atomic():
        locked = _locked_deposit(access, deposit, DepositStatus.RECEIVED)
        locked.status = DepositStatus.CHECKING
        locked.save(update_fields=["status", "updated_at"])
        record_event(
            DEPOSIT_CHECK_STARTED,
            Change(
                DEPOSIT,
                locked.public_id,
                {"status": [DepositStatus.RECEIVED, DepositStatus.CHECKING]},
                lab_id=locked.lab_id,
            ),
        )
    return locked


def deposit_accept(*, access: Access, deposit: Deposit, facts: StrainFacts) -> Deposit:
    """The check passed: the strain is created with its number and the biosafety gates of
    the strain service, and the material as received becomes its passage 0."""
    with audited_atomic():
        locked = _locked_deposit(access, deposit, DepositStatus.CHECKING)
        lab = Lab.objects.get(pk=locked.lab_id)
        strain = strains.strain_create(
            access=access,
            lab=lab,
            data=strains.NewStrain(
                name_as_received=locked.name_as_received,
                taxon=facts.taxon,
                identified_on=facts.identified_on,
                identification_method=facts.identification_method,
                risk_group=facts.risk_group,
                animal_pathogenicity=facts.animal_pathogenicity,
                plant_pathogenicity=facts.plant_pathogenicity,
                isolation_source=facts.isolation_source,
                country_of_origin=facts.country_of_origin,
                isolation_date=facts.isolation_date,
                restrictions=facts.restrictions,
            ),
        )
        locked.status, locked.strain, locked.decided_at = (
            DepositStatus.ACCEPTED,
            strain,
            timezone.now(),
        )
        locked.save(update_fields=["status", "strain", "decided_at", "updated_at"])
        record_event(
            DEPOSIT_ACCEPTED,
            Change(
                DEPOSIT,
                locked.public_id,
                {
                    "status": [DepositStatus.CHECKING, DepositStatus.ACCEPTED],
                    "strain": [None, str(strain.public_id)],
                    "accession_number": [None, strain.accession_number],
                },
                lab_id=locked.lab_id,
                strain_id=strain.public_id,
            ),
        )
        passage = Passage.objects.create(
            lab_id=locked.lab_id, strain=strain, number=0, source_deposit=locked
        )
        record_event(
            PASSAGE_CREATED,
            Change(
                PASSAGE,
                passage.public_id,
                {"number": [None, 0], "source_deposit": [None, str(locked.public_id)]},
                lab_id=locked.lab_id,
                strain_id=strain.public_id,
            ),
        )
    return locked


def deposit_reject(*, access: Access, deposit: Deposit, reason: str) -> Deposit:
    """The check failed: the deposit ends here, with the reason, and no number is taken."""
    reason = _check_reason(reason)
    with audited_atomic():
        locked = _locked_deposit(access, deposit, DepositStatus.CHECKING)
        locked.status, locked.rejection_reason, locked.decided_at = (
            DepositStatus.REJECTED,
            reason,
            timezone.now(),
        )
        locked.save(update_fields=["status", "rejection_reason", "decided_at", "updated_at"])
        record_event(
            DEPOSIT_REJECTED,
            Change(
                DEPOSIT,
                locked.public_id,
                {"status": [DepositStatus.CHECKING, DepositStatus.REJECTED]},
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
    return locked

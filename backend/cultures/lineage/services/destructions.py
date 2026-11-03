"""The destruction of material (#160): a record per strain per destruction, the only way a vial
becomes destroyed (ADR 0008 and ADR 0009, amendments of 2026-11-03).

What the record asks depends on the strain's active restrictions (strains.selectors.
regulating_restrictions, the union of their kinds), from the destruction study s12 and Mirek's
decisions of 2026-11-02:

- every strain: the vials marked to destroy, the Czech day, a method code (Q5) and the reason;
  an outside firm only with the number of its handover document (Q9);
- every regulated kind: a verification of the inactivation (Q4), and a manager other than the
  recorder confirms the record, which destroys the vials (Q2, ADR 0009: "No single account can
  destroy, deaccession or ship a regulated strain"; WHO Laboratory biosecurity guidance 2024,
  p. 31, "removal of biological material from the inventory by two employees");
- cz_vrat: the witness present at the destruction, a member other than the recorder (Q2);
- cz_vrat and cz_rat: the material inactivated in the lab before an outside firm takes it (Q9;
  act 281/2002 Sb., § 13 h) gives VRAT only to a permit holder, and SÚJB gives RAT only to
  persons who notified RAT handling under § 17a, owner's decision of 2026-11-03);
- quarantine_pest: the method the lab's ÚKZÚZ permit declares (Q6; Regulation (EU) 2019/829,
  Annex I (i)).

A strain that is not regulated is destroyed by one person at recording. A record is never
changed or deleted; a wrong one is entered in error with a reason (decree 474/2002 Sb., § 5(4)).
A record entered in error before its confirmation leaves its vials to destroy, for a new record.

Lock order, as every lineage service: the lab, the strain, the record, the vials by pk, their
placements. Under the lab lock each service re-reads the actor's role and the strain's
restrictions, which change under the same lock (strains.services). The database holds the shape
on its own (migration 0014): who may confirm, the kinds' rules, vials destroyed only together
with their completed record.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from django.db import connection
from django.db.models import Max
from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_batch, record_event
from cultures.audit.registry import (
    DESTRUCTION_CONFIRMED,
    DESTRUCTION_ENTERED_IN_ERROR,
    DESTRUCTION_RECORDED,
    VIAL_STATUS_CHANGED,
    VIALS_DESTROYED,
)
from cultures.biosafety.models import (
    AuthorisationKind,
    DestructionMethod,
    LabAuthorisation,
    RestrictionKind,
)
from cultures.biosafety.policy import PERMIT_TIME_ZONE, permit_today, valid_on
from cultures.core.exceptions import Conflict, DomainError, NotFound
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Membership
from cultures.labs.permissions import Perm, Role, role_has
from cultures.strains.models import Strain
from cultures.strains.selectors import regulating_restrictions
from cultures.users.models import User

from ..models import (
    DESTRUCTION_NUMBER_UNIQUE,
    DestructionRecord,
    DestructionStatus,
    DestructionVial,
    RemovalReason,
    Vial,
    VialStatus,
)
from ._shared import VIAL, _check_reason, _close, _open_placement, _require, _save, _where
from .errors import (
    AuthorisationMethodMissing,
    ConfirmOwnDestruction,
    DestructionEnteredInError,
    DestructionNotAwaiting,
    DestructionOutdated,
    InvalidDestruction,
    VialInDestruction,
    VialNotToDestroy,
)

STRAIN = "strain"
DETAIL_LENGTH = 200
VERIFICATION_LENGTH = 500
CONTRACTOR_LENGTH = 200
DOCUMENT_LENGTH = 100
RUN_LENGTH = 100


@dataclass(frozen=True)
class Required:
    """What a destruction record of a strain needs, from its active restriction kinds."""

    kinds: frozenset[RestrictionKind]

    @property
    def confirmation(self) -> bool:
        """ADR 0009: every regulated kind."""
        return bool(self.kinds)

    @property
    def verification(self) -> bool:
        """Decision Q4: every regulated kind."""
        return bool(self.kinds)

    @property
    def witness(self) -> bool:
        """Decision Q2: a VRAT."""
        return RestrictionKind.CZ_VRAT in self.kinds

    @property
    def inactivated_before_handover(self) -> bool:
        """Decision Q9 and the owner's decision of 2026-11-03: a VRAT or a RAT."""
        return bool(self.kinds & {RestrictionKind.CZ_VRAT, RestrictionKind.CZ_RAT})

    @property
    def authorised_method(self) -> bool:
        """Decision Q6: a quarantine pest."""
        return RestrictionKind.QUARANTINE_PEST in self.kinds


def required_for(strain: Strain) -> Required:
    """The strain's active kinds as committed now. Under the lab lock, a decision; outside it, a
    hint for a screen."""
    kinds = regulating_restrictions().filter(strain=strain).values_list("kind", flat=True)
    return Required(frozenset(RestrictionKind(k) for k in kinds))


@dataclass(frozen=True)
class NewDestruction:
    """A destruction as the person recorded it. Free text names no person."""

    vials: Sequence[Vial]
    destroyed_on: date
    method: DestructionMethod
    reason: str
    method_detail: str = ""
    verification: str = ""
    contractor: str = ""
    handover_document: str = ""
    inactivated_in_lab: bool = True
    run: str = ""
    witness: User | None = field(default=None)


def _text(value: str, limit: int, attr: str) -> str:
    text = " ".join(value.split())
    if len(text) > limit:
        raise InvalidDestruction(f"At most {limit} characters.", code="max_length", attr=attr)
    return text


def _checked_input(data: NewDestruction) -> NewDestruction:
    """The input alone, before any lock."""
    reason = _check_reason(data.reason)
    if data.method not in DestructionMethod.values:
        raise InvalidDestruction("Choose how the material was destroyed.", attr="method")
    detail = _text(data.method_detail, DETAIL_LENGTH, "method_detail")
    if data.method == DestructionMethod.OTHER and not detail:
        raise InvalidDestruction("Describe the method.", code="required", attr="method_detail")
    if data.destroyed_on > permit_today():
        raise InvalidDestruction("This date is in the future.", attr="destroyed_on")
    contractor = _text(data.contractor, CONTRACTOR_LENGTH, "contractor")
    document = _text(data.handover_document, DOCUMENT_LENGTH, "handover_document")
    if contractor and not document:
        raise InvalidDestruction(
            "Give the number of the document the firm signed for the material.",
            code="required",
            attr="handover_document",
        )
    if document and not contractor:
        raise InvalidDestruction(
            "Name the firm the material was handed to.", code="required", attr="contractor"
        )
    if not contractor and not data.inactivated_in_lab:
        raise InvalidDestruction(
            "Without an outside firm the lab destroyed the material itself.",
            attr="inactivated_in_lab",
        )
    if not data.vials:
        raise InvalidDestruction("Choose at least one vial.", code="required", attr="vials")
    seen: set[int] = set()
    for i, vial in enumerate(data.vials):
        if vial.pk in seen:
            raise InvalidDestruction(
                "This vial is in the list twice.", code="duplicate", attr=f"vials.{i}"
            )
        seen.add(vial.pk)
    return replace(
        data,
        reason=reason,
        method_detail=detail,
        verification=_text(data.verification, VERIFICATION_LENGTH, "verification"),
        contractor=contractor,
        handover_document=document,
        run=_text(data.run, RUN_LENGTH, "run"),
    )


def _declaring_authorisation(lab_id: int, day: date, method: str) -> LabAuthorisation:
    """The lab's ÚKZÚZ permit whose declared method the record uses: one in force on the day of
    the destruction, else the last one that started before it (material is destroyed when the
    activity ends, after a permit too: Regulation (EU) 2019/829, Art. 5 (d)). Refuses another
    method (decision Q6): a change of method is first notified to ÚKZÚZ (its guide for
    confinement facilities: "Oznámit ÚKZÚZ jakékoliv změny týkající se informací uvedených v
    rozhodnutí")."""
    held = LabAuthorisation.objects.filter(
        lab_id=lab_id, kind=AuthorisationKind.QUARANTINE_PEST, valid_from__lte=day
    ).order_by("-valid_from", "-pk")
    candidates = list(held.filter(valid_on(day))) or list(held[:1])
    if not candidates:
        raise InvalidDestruction(
            "The lab held no ÚKZÚZ permit for quarantine pests on that day.",
            code="lab_authorisation_required",
            attr="destroyed_on",
        )
    for authorisation in candidates:
        if authorisation.destruction_method == method:
            return authorisation
    declared = [a for a in candidates if a.destruction_method]
    if not declared:
        raise AuthorisationMethodMissing
    first = declared[0]
    label = DestructionMethod(first.destruction_method).label.lower()
    raise InvalidDestruction(
        f"The lab's ÚKZÚZ permit {first.permit_reference} declares {label}: a quarantine pest is"
        " destroyed by that method. A change of method is notified to ÚKZÚZ first.",
        code="method_not_authorised",
        attr="method",
    )


def _check_rules(
    required: Required, data: NewDestruction, recorder: User, lab_id: int
) -> LabAuthorisation | None:
    """The kinds' rules. Caller holds the lab lock. Returns the declaring permit of a quarantine
    pest."""
    if required.verification and not data.verification:
        raise InvalidDestruction(
            "Say how the inactivation was verified: the strain is regulated.",
            code="required",
            attr="verification",
        )
    if required.witness and data.witness is None:
        raise InvalidDestruction(
            "Name the member who witnessed the destruction: the strain is a highly risky agent"
            " (VRAT).",
            code="required",
            attr="witness",
        )
    if data.witness is not None and data.witness.pk == recorder.pk:
        raise InvalidDestruction(
            "The witness is a member other than you.", code="witness_is_recorder", attr="witness"
        )
    if required.inactivated_before_handover and data.contractor and not data.inactivated_in_lab:
        raise InvalidDestruction(
            "A highly risky or risky agent (VRAT, RAT) is inactivated in the lab before a firm"
            " takes it: the act gives VRAT only to a permit holder (act 281/2002 Sb., § 13 h)), and"
            " RAT only to persons who notified RAT handling (§ 17a).",
            code="inactivate_before_handover",
            attr="inactivated_in_lab",
        )
    if required.authorised_method:
        return _declaring_authorisation(lab_id, data.destroyed_on, data.method)
    return None


def _check_witness(witness: User | None, lab_id: int) -> None:
    """An active member who handles vials in the lab, as committed now (under the lab lock).
    Anyone else gives the same error as an unknown member."""
    if witness is None:
        return
    role = (
        Membership.objects.filter(lab_id=lab_id, user=witness, user__is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    if role is None or not role_has(Role(role), Perm.HANDLE_VIALS):
        raise InvalidDestruction("Invalid member.", code="does_not_exist", attr="witness")


def _locked_strain(strain_id: int) -> Strain:
    strain = Strain.objects.select_for_update().filter(pk=strain_id).first()
    if strain is None:
        raise NotFound
    return strain


def _locked_vials(data: NewDestruction, strain: Strain) -> list[Vial]:
    """The vials as committed now, locked in pk order: each of the strain, to destroy and in no
    valid record. Refusals name the entry by its index in `vials`."""
    ids = [v.pk for v in data.vials]
    locked = {
        v.pk: v
        for v in Vial.objects.select_for_update(of=("self",))
        .select_related("batch__strain")
        .filter(pk__in=ids, batch__strain=strain)
        .order_by("pk")
    }
    held = set(
        DestructionVial.objects.filter(
            vial_id__in=ids, record__status=DestructionStatus.VALID
        ).values_list("vial_id", flat=True)
    )
    for i, vial in enumerate(data.vials):
        found = locked.get(vial.pk)
        attr = f"vials.{i}"
        if found is None:
            raise InvalidDestruction("Invalid vial.", code="does_not_exist", attr=attr)
        if found.status != VialStatus.TO_DESTROY:
            raise VialNotToDestroy(attr=attr)
        if found.pk in held:
            raise VialInDestruction(attr=attr)
        assert found.status_changed_at is not None  # noqa: S101 (marked to destroy once)
        if data.destroyed_on < found.status_changed_at.astimezone(PERMIT_TIME_ZONE).date():
            raise InvalidDestruction(
                "The destruction is not dated before the vial was marked to destroy.",
                attr="destroyed_on",
            )
    return [locked[v.pk] for v in data.vials]


def _defer_destruction_checks() -> None:
    """The record is written before its vials, and its vials before their destroyed state: the
    triggers that hold them together check at commit (migration 0014), also in a session that
    set its constraints immediate."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SET CONSTRAINTS lineage_destruction_complete, lineage_vial_destroyed_by_record"
            " DEFERRED"
        )


def _values(record: DestructionRecord, vials: Sequence[Vial]) -> dict[str, Any]:
    """What the events hold: ids, codes and texts that name nobody. The firm is only `outside`
    (its name may be a sole trader's), the witness a public id (ADR 0005)."""
    return {
        "public_id": str(record.public_id),
        "number": record.label,
        "destroyed_on": record.destroyed_on.isoformat(),
        "method": record.method,
        "method_detail": record.method_detail,
        "verification": record.verification,
        "outside_firm": bool(record.contractor),
        "handover_document": record.handover_document,
        "inactivated_in_lab": record.inactivated_in_lab,
        "run": record.run,
        "witness": str(record.witness.public_id) if record.witness else None,
        "authorisation": str(record.authorisation.public_id) if record.authorisation else None,
        "vials": [str(v.public_id) for v in vials],
    }


def _complete(record: DestructionRecord, vials: Sequence[Vial], access: Access) -> None:
    """The vials go destroyed at the record's completed_at and leave their places, in this
    transaction. One vial_status_changed each and one vials_destroyed, with the record's
    reason."""
    assert record.completed_at is not None  # noqa: S101 (the caller completed it)
    now = record.completed_at
    changes = []
    for vial in vials:
        old = VialStatus(vial.status)
        moved: dict[str, Any] = {"status": [old, VialStatus.DESTROYED]}
        placement = _open_placement(vial)
        if placement is not None:
            _close(placement, access, RemovalReason.DESTROYED, now)
            moved["location"] = [_where(placement), None]
        moved["destruction"] = [None, str(record.public_id)]
        vial.status, vial.status_changed_at = VialStatus.DESTROYED, now
        vial.save(update_fields=["status", "status_changed_at", "updated_at"])
        changes.append(
            Change(
                VIAL,
                vial.public_id,
                moved,
                lab_id=vial.lab_id,
                strain_id=record.strain.public_id,
            )
        )
    record_batch(VIAL_STATUS_CHANGED, VIALS_DESTROYED, changes, reason=record.reason)


def _next_number(lab_id: int, year: int) -> int:
    """Caller holds the lab lock: no other record of the lab is numbered meanwhile."""
    top = DestructionRecord.objects.filter(lab_id=lab_id, year=year).aggregate(top=Max("number"))
    return int(top["top"] or 0) + 1


def destruction_record(
    *, access: Access, strain: Strain, data: NewDestruction
) -> DestructionRecord:
    """Records the destruction of vials of one strain (technicians and up, vials.handle). A strain
    that is not regulated is destroyed now: its vials go destroyed and leave their places. A
    regulated one waits for a manager other than the recorder (destruction_confirm)."""
    data = _checked_input(data)
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require(access, strain.lab_id)
        locked = _locked_strain(strain.pk)
        required = required_for(locked)
        vials = _locked_vials(data, locked)
        _check_witness(data.witness, locked.lab_id)
        authorisation = _check_rules(required, data, access.user, locked.lab_id)
        _defer_destruction_checks()
        now = timezone.now()
        year = permit_today().year
        record = DestructionRecord(
            lab_id=locked.lab_id,
            strain=locked,
            year=year,
            number=_next_number(locked.lab_id, year),
            destroyed_on=data.destroyed_on,
            method=data.method,
            method_detail=data.method_detail,
            verification=data.verification,
            contractor=data.contractor,
            handover_document=data.handover_document,
            inactivated_in_lab=data.inactivated_in_lab,
            run=data.run,
            reason=data.reason,
            witness=data.witness,
            authorisation=authorisation,
            recorded_by=access.user,
            recorded_at=now,
            completed_at=None if required.confirmation else now,
        )
        # The lab lock serialises numbering; the constraint is the final arbiter.
        _save(
            record,
            {
                DESTRUCTION_NUMBER_UNIQUE: Conflict(
                    "Another record took this number at the same moment: try again."
                )
            },
        )
        DestructionVial.objects.bulk_create(
            [DestructionVial(lab_id=locked.lab_id, record=record, vial=v) for v in vials]
        )
        record_event(
            DESTRUCTION_RECORDED,
            Change(
                STRAIN,
                locked.public_id,
                {
                    "destruction": [None, _values(record, vials)],
                    "awaits_confirmation": [None, required.confirmation],
                },
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=data.reason,
        )
        if not required.confirmation:
            _complete(record, vials, access)
    return record


def _locked_record(record: DestructionRecord) -> DestructionRecord:
    locked = (
        DestructionRecord.objects.select_for_update(of=("self",))
        .select_related("strain", "witness", "authorisation", "recorded_by")
        .filter(pk=record.pk)
        .first()
    )
    if locked is None:
        raise NotFound
    return locked


def _record_vials(record: DestructionRecord) -> list[Vial]:
    return list(
        Vial.objects.select_for_update(of=("self",))
        .select_related("batch__strain")
        .filter(destructions__record=record)
        .order_by("pk")
    )


def destruction_confirm(*, access: Access, record: DestructionRecord) -> DestructionRecord:
    """A manager other than the recorder confirms a regulated strain's record (ADR 0009,
    decision Q2): its vials are destroyed now. Refused when the strain's restrictions changed
    so that the record no longer holds what they ask."""
    with audited_atomic():
        lock_lab(record.lab_id)
        _require(access, record.lab_id, Perm.CONFIRM_DESTRUCTION)
        _locked_strain(record.strain_id)
        locked = _locked_record(record)
        if locked.status != DestructionStatus.VALID or locked.completed_at is not None:
            raise DestructionNotAwaiting
        if locked.recorded_by_id == access.user.pk:
            raise ConfirmOwnDestruction
        vials = _record_vials(locked)
        as_recorded = NewDestruction(
            vials=vials,
            destroyed_on=locked.destroyed_on,
            method=DestructionMethod(locked.method),
            reason=locked.reason,
            method_detail=locked.method_detail,
            verification=locked.verification,
            contractor=locked.contractor,
            handover_document=locked.handover_document,
            inactivated_in_lab=locked.inactivated_in_lab,
            run=locked.run,
            witness=locked.witness,
        )
        required = required_for(locked.strain)
        try:
            authorisation = _check_rules(required, as_recorded, locked.recorded_by, locked.lab_id)
        except DomainError:
            raise DestructionOutdated from None
        if authorisation is not None and authorisation.pk != locked.authorisation_id:
            raise DestructionOutdated
        if any(v.status != VialStatus.TO_DESTROY for v in vials):
            raise DestructionOutdated  # the trigger holds them to destroy; a guard
        _defer_destruction_checks()
        now = timezone.now()
        locked.confirmed_by, locked.confirmed_at, locked.completed_at = access.user, now, now
        locked.save(update_fields=["confirmed_by", "confirmed_at", "completed_at", "updated_at"])
        record_event(
            DESTRUCTION_CONFIRMED,
            Change(
                STRAIN,
                locked.strain.public_id,
                {
                    "destruction": [None, str(locked.public_id)],
                    # Pseudonymous: public ids, never names (ADR 0005).
                    "recorded_by": [None, str(locked.recorded_by.public_id)],
                    "recorded_at": [None, locked.recorded_at.isoformat()],
                    "confirmed_by": [None, str(access.user.public_id)],
                    "confirmed_at": [None, now.isoformat()],
                },
                lab_id=locked.lab_id,
                strain_id=locked.strain.public_id,
            ),
            reason=locked.reason,
        )
        _complete(locked, vials, access)
    return locked


def destruction_enter_in_error(
    *, access: Access, record: DestructionRecord, reason: str
) -> DestructionRecord:
    """A wrong record stays readable, marked entered in error with the reason (decree 474/2002
    Sb., § 5(4)). Before its confirmation anyone who handles vials does it, and its vials stay to
    destroy for a new record. A record that destroyed vials leaves them destroyed: the material
    is gone. A confirmed one is a manager's (vials.confirm_destruction), as its confirmation."""
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(record.lab_id)
        _require(access, record.lab_id)
        _locked_strain(record.strain_id)
        locked = _locked_record(record)
        if locked.status != DestructionStatus.VALID:
            raise DestructionEnteredInError
        if locked.confirmed_at is not None:
            _require(access, record.lab_id, Perm.CONFIRM_DESTRUCTION)
        now = timezone.now()
        locked.status = DestructionStatus.ENTERED_IN_ERROR
        locked.error_reason = reason
        locked.entered_in_error_by, locked.entered_in_error_at = access.user, now
        locked.save(
            update_fields=[
                "status",
                "error_reason",
                "entered_in_error_by",
                "entered_in_error_at",
                "updated_at",
            ]
        )
        record_event(
            DESTRUCTION_ENTERED_IN_ERROR,
            Change(
                STRAIN,
                locked.strain.public_id,
                {
                    "destruction": [str(locked.public_id), None],
                    "vials_destroyed": [None, locked.completed_at is not None],
                },
                lab_id=locked.lab_id,
                strain_id=locked.strain.public_id,
            ),
            reason=reason,
        )
    return locked

"""Every write on strains: accession, reclassification, risk group and restrictions.

Each service runs in audited_atomic() and records one event that names the
strain (Change(strain_id=...), ADR 0008, D13). Lock order, as everywhere: the
lab row first (labs.locks.lock_lab), then the strain's rows. Under the lab
lock each service
- re-reads the actor's role in the lab, so a curator demoted after the request
  built its access object is refused (the members services do the same);
- checks the lab's permits for a cz_vrat or quarantine_pest restriction
  (biosafety.policy), so a permit ended at the same moment is seen;
- takes the next accession number from the lab's counter row, so two
  accessions never get the same number, also when they run at once.
A refusal raises before anything is written, or rolls back what was, so it
changes nothing and records nothing.

Rules (ADR 0009): a risk group 4 agent is refused, at accession and as a
change, and so is a group above the cap of a box holding the strain's vials.
A changed risk group, a reclassification, an added or an ended restriction
each need a reason (audit.registry, reason_required). A restriction ends in two
steps by two people (#105): someone who manages strains proposes it, a manager
other than the proposer confirms it.
"""

import re
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Model
from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    STRAIN_CREATED,
    STRAIN_DEACCESSION_PROPOSED,
    STRAIN_DEACCESSION_WITHDRAWN,
    STRAIN_DEACCESSIONED,
    STRAIN_GROWTH_CHANGED,
    STRAIN_RECLASSIFIED,
    STRAIN_RESTRICTION_ADDED,
    STRAIN_RESTRICTION_END_PROPOSED,
    STRAIN_RESTRICTION_END_WITHDRAWN,
    STRAIN_RESTRICTION_ENDED,
    STRAIN_RISK_GROUP_CHANGED,
)
from cultures.biosafety.models import RestrictionKind
from cultures.biosafety.policy import permit_today, require_authorisation
from cultures.core.exceptions import Conflict, DomainError, Forbidden, NotFound, RuleViolation
from cultures.distribution import services as distribution
from cultures.growth.services import Growth, growth_fields, growth_of, growth_values, locked_growth
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Perm, Role, role_has
from cultures.lineage import services as lineage
from cultures.lineage.models import VialPlacement
from cultures.storage.models import StorageUnit
from cultures.taxonomy.models import Taxon

from .countries import COUNTRY_CODES
from .models import (
    ACCESSION_NUMBER_UNIQUE,
    ACCESSION_SEQ_UNIQUE,
    ACTIVE_RESTRICTION_UNIQUE,
    DUAL_USE_ENTRY,
    EU_ACT,
    KEEPS_MATERIAL,
    ONE_OPEN_DEACCESSION_PROPOSAL,
    PARTIAL_DATE,
    DeaccessionCause,
    FinalUse,
    Pathogenicity,
    RestrictionEndProposal,
    Strain,
    StrainCounter,
    StrainDeaccessionProposal,
    StrainIdentification,
    StrainRestriction,
    StrainStatus,
)
from .selectors import regulating_restrictions

STRAIN = "strain"
RISK_GROUP_REFUSED = 4
ACCESSION_REASON = "Identification at accession"
MAX_RESTRICTIONS = 10


class InvalidStrain(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class RiskGroupRefused(DomainError):
    """A field error on purpose: the form shows it on the risk group."""

    default_code = "risk_group_4_refused"
    default_detail = "The collection does not hold risk group 4 agents."

    def __init__(self, detail: str | None = None, *, attr: str | None = "risk_group") -> None:
        super().__init__(detail, attr=attr)


class RiskGroupAboveBoxCap(DomainError):
    """A field error on the risk group. Names no box: a regulated strain's place stays masked."""

    default_code = "risk_group_above_box_cap"
    default_detail = "A box holding this strain's vials does not allow this risk group."

    def __init__(self, detail: str | None = None, *, attr: str | None = "risk_group") -> None:
        super().__init__(detail, attr=attr)


class AccessionTaken(Conflict):
    default_code = "accession_taken"
    default_detail = "This accession number is taken: try again."


class RestrictionEnded(Conflict):
    default_code = "restriction_ended"
    default_detail = "This restriction has ended already."


class EndProposed(Conflict):
    """One open proposal per restriction: the second one waits for the first to be settled."""

    default_code = "end_proposed"
    default_detail = "Someone has proposed to end this restriction already."


class EndNotProposed(Conflict):
    default_code = "end_not_proposed"
    default_detail = "Nobody has proposed to end this restriction, or the proposal was settled."


class EndProposalChanged(Conflict):
    """The confirmation names the proposal the manager read; another one is open now."""

    default_code = "end_proposal_changed"
    default_detail = "The proposal changed meanwhile. Read it again before you confirm."


class ConfirmOwnEndProposal(Forbidden):
    """ADR 0009 (#105): nobody confirms the end of a restriction they proposed."""

    default_code = "confirm_own_end_proposal"
    default_detail = "You proposed to end this restriction: a different manager confirms it."


class StrainDeaccessioned(Conflict):
    """#20: deaccessioned is terminal. The strain and its history stay; nothing of it changes."""

    default_code = "strain_deaccessioned"
    default_detail = "This strain has left the collection: it changes no more."


class StrainPending(Conflict):
    default_code = "strain_pending"
    default_detail = "This strain is not in the collection yet."


class DeaccessionNeedsSecondPerson(RuleViolation):
    """ADR 0009 (#20): a regulated strain leaves the collection by two people."""

    default_code = "second_person_required"
    default_detail = (
        "This strain is regulated: propose the deaccession, and a manager other than you"
        " confirms it."
    )


class DeaccessionInOneStep(RuleViolation):
    default_code = "deaccession_in_one_step"
    default_detail = "This strain is not regulated: deaccession it in one step."


class DeaccessionProposed(Conflict):
    """One open proposal per strain: the second one waits for the first to be settled."""

    default_code = "deaccession_proposed"
    default_detail = "Someone has proposed to deaccession this strain already."


class DeaccessionNotProposed(Conflict):
    default_code = "deaccession_not_proposed"
    default_detail = "Nobody has proposed to deaccession this strain, or the proposal was settled."


class DeaccessionProposalChanged(Conflict):
    """The confirmation names the proposal the manager read; another one is open now."""

    default_code = "deaccession_proposal_changed"
    default_detail = "The proposal changed meanwhile. Read it again before you confirm."


class DeaccessionProposalOutdated(Conflict):
    """The final use the proposal states no longer fits the strain's restrictions."""

    default_code = "deaccession_proposal_outdated"
    default_detail = (
        "The strain's restrictions changed since the proposal: withdraw it and propose again."
    )


class ConfirmOwnDeaccession(Forbidden):
    """ADR 0009 (#20): nobody confirms the deaccession they proposed."""

    default_code = "confirm_own_deaccession"
    default_detail = "You proposed to deaccession this strain: a different manager confirms it."


@dataclass(frozen=True)
class Deaccession:
    """Why a strain leaves: the cause, the reason in words, and for a quarantine pest the final
    use (Regulation (EU) 2019/829, Annex I (h))."""

    cause: DeaccessionCause
    reason: str
    final_use: FinalUse | None = None


@dataclass(frozen=True)
class RestrictionInput:
    kind: RestrictionKind
    reference: str
    act: str = ""
    gmo_category: int | None = None


@dataclass(frozen=True)
class NewStrain:
    name_as_received: str
    taxon: Taxon
    identified_on: date
    identification_method: str
    risk_group: int
    animal_pathogenicity: Pathogenicity = Pathogenicity.UNKNOWN
    plant_pathogenicity: Pathogenicity = Pathogenicity.UNKNOWN
    isolation_source: str = ""
    country_of_origin: str = ""
    isolation_date: str = ""
    restrictions: Sequence[RestrictionInput] = field(default_factory=tuple)


def normalised(text: str) -> str:
    """One space between words, NFC."""
    return " ".join(unicodedata.normalize("NFC", text).split())


# Checks on the input alone: no query, so they run before any lock.


def _check_risk_group(risk_group: int, attr: str = "risk_group") -> None:
    if risk_group == RISK_GROUP_REFUSED:
        raise RiskGroupRefused(attr=attr)
    if risk_group not in (1, 2, 3):
        raise InvalidStrain("A risk group is 1, 2 or 3.", attr=attr)


def _check_not_future(day: date, attr: str) -> None:
    if day > permit_today():
        raise InvalidStrain("This date is in the future.", attr=attr)


def check_partial_date(text: str, attr: str) -> None:
    """YYYY, YYYY-MM or YYYY-MM-DD, a real day, not after today."""
    if not text:
        return
    if not re.fullmatch(PARTIAL_DATE, text):
        raise InvalidStrain("Use YYYY, YYYY-MM or YYYY-MM-DD.", attr=attr)
    parts = [int(p) for p in text.split("-")]
    try:
        first = date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)  # noqa: PLR2004
    except ValueError:
        raise InvalidStrain("This day does not exist.", attr=attr) from None
    if first > permit_today():
        raise InvalidStrain("This date is in the future.", attr=attr)


def check_restriction(restriction: RestrictionInput, prefix: str = "") -> RestrictionInput:
    """The fields a kind needs, and only those. Returns it normalised."""
    reference = normalised(restriction.reference)
    act = normalised(restriction.act)
    if not reference:
        raise InvalidStrain("Enter the list entry.", attr=f"{prefix}reference")
    if restriction.kind == RestrictionKind.DUAL_USE:
        if not re.fullmatch(DUAL_USE_ENTRY, reference):
            raise InvalidStrain(
                "Enter an Annex I entry of 1C351, 1C353 or 1C354, for example 1C351.c.",
                attr=f"{prefix}reference",
            )
        if not re.fullmatch(EU_ACT, act):
            raise InvalidStrain(
                "Enter the act Annex I was read in, for example (EU) 2025/2003.",
                attr=f"{prefix}act",
            )
    elif act:
        raise InvalidStrain("Only a dual-use item names an act.", attr=f"{prefix}act")
    if restriction.kind == RestrictionKind.GMO:
        if restriction.gmo_category not in (1, 2, 3, 4):
            raise InvalidStrain("Choose the category, I to IV.", attr=f"{prefix}gmo_category")
    elif restriction.gmo_category is not None:
        raise InvalidStrain("Only a GMO has a category.", attr=f"{prefix}gmo_category")
    return RestrictionInput(restriction.kind, reference, act, restriction.gmo_category)


def _checked(data: NewStrain) -> NewStrain:
    name = normalised(data.name_as_received)
    if not name:
        raise InvalidStrain("Enter the name as received.", attr="name_as_received")
    method = normalised(data.identification_method)
    if not method:
        raise InvalidStrain("Enter how it was identified.", attr="identification_method")
    _check_risk_group(data.risk_group)
    _check_not_future(data.identified_on, "identified_on")
    if data.country_of_origin and data.country_of_origin not in COUNTRY_CODES:
        raise InvalidStrain("Choose a country.", attr="country_of_origin")
    check_partial_date(data.isolation_date, "isolation_date")
    if len(data.restrictions) > MAX_RESTRICTIONS:
        raise InvalidStrain(f"At most {MAX_RESTRICTIONS} restrictions.", attr="restrictions")
    restrictions = [
        check_restriction(r, prefix=f"restrictions.{i}.") for i, r in enumerate(data.restrictions)
    ]
    seen: set[tuple[str, str]] = set()
    for i, r in enumerate(restrictions):
        key = (r.kind, r.reference.upper())
        if key in seen:
            raise InvalidStrain(
                "This restriction is listed twice.", attr=f"restrictions.{i}.reference"
            )
        seen.add(key)
    return NewStrain(
        name_as_received=name,
        taxon=data.taxon,
        identified_on=data.identified_on,
        identification_method=method,
        risk_group=data.risk_group,
        animal_pathogenicity=data.animal_pathogenicity,
        plant_pathogenicity=data.plant_pathogenicity,
        isolation_source=normalised(data.isolation_source),
        country_of_origin=data.country_of_origin,
        isolation_date=data.isolation_date,
        restrictions=tuple(restrictions),
    )


def _check_reason(reason: str) -> str:
    """Before any write: the identification row and the event both need one."""
    if not reason.strip():
        raise RuleViolation("A reason is required.", code="reason_required", attr="reason")
    return reason.strip()


# Under the lab lock.


def _require_role(access: Access, lab_id: int, perm: Perm = Perm.MANAGE_STRAINS) -> None:
    """The actor's role as committed now (caller holds the lab lock), not as the request began."""
    role = (
        Membership.objects.filter(lab_id=lab_id, user=access.user, user__is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    if role is None or not role_has(Role(role), perm):
        raise Forbidden


def _next_seq(lab: Lab) -> int:
    """The lab's next accession sequence. Caller holds the lab lock; the counter row is locked
    too, so a writer that skipped the lab lock still waits here."""
    counter = StrainCounter.objects.select_for_update().filter(lab=lab).first()
    if counter is None:
        counter = StrainCounter.objects.create(lab=lab, last_seq=0)
    counter.last_seq += 1
    counter.save(update_fields=["last_seq"])
    return counter.last_seq


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


def _restriction_values(r: StrainRestriction | RestrictionInput) -> dict[str, Any]:
    return {"kind": r.kind, "reference": r.reference, "act": r.act, "gmo_category": r.gmo_category}


def _locked_strain(strain: Strain) -> Strain:
    """The strain locked, in the collection: a deaccessioned one changes no more (#20)."""
    locked = Strain.objects.select_for_update().filter(pk=strain.pk).select_related("lab").first()
    if locked is None:
        raise NotFound
    if locked.status == StrainStatus.DEACCESSIONED:
        raise StrainDeaccessioned
    if locked.status == StrainStatus.PENDING:
        raise StrainPending
    return locked


def strain_create(*, access: Access, lab: Lab, data: NewStrain) -> Strain:
    """A curator's direct accession (ADR 0008, D8, until deposit intake exists): the strain
    is active at once and gets its number, "<lab code> <seq>", which never changes."""
    data = _checked(data)
    with audited_atomic():
        locked_lab = lock_lab(lab.pk)
        _require_role(access, locked_lab.pk)
        require_authorisation(
            lab_id=locked_lab.pk,
            kinds=[(r.kind, f"restrictions.{i}.kind") for i, r in enumerate(data.restrictions)],
        )
        seq = _next_seq(locked_lab)
        strain = Strain(
            lab=locked_lab,
            accession_number=f"{locked_lab.code} {seq}",
            accession_seq=seq,
            status=StrainStatus.ACTIVE,
            name_as_received=data.name_as_received,
            taxon=data.taxon,
            risk_group=data.risk_group,
            animal_pathogenicity=data.animal_pathogenicity,
            plant_pathogenicity=data.plant_pathogenicity,
            isolation_source=data.isolation_source,
            country_of_origin=data.country_of_origin,
            isolation_date=data.isolation_date,
        )
        taken = AccessionTaken()
        _save(strain, {ACCESSION_NUMBER_UNIQUE: taken, ACCESSION_SEQ_UNIQUE: taken})
        identification = StrainIdentification.objects.create(
            lab=locked_lab,
            strain=strain,
            taxon=data.taxon,
            identified_on=data.identified_on,
            method=data.identification_method,
            reason=ACCESSION_REASON,
            is_current=True,
        )
        for r in data.restrictions:
            StrainRestriction.objects.create(
                lab=locked_lab, strain=strain, **_restriction_values(r)
            )
        values: dict[str, Any] = {
            "accession_number": strain.accession_number,
            "status": strain.status,
            "name_as_received": strain.name_as_received,
            "taxon": str(data.taxon.public_id),
            "risk_group": strain.risk_group,
            "animal_pathogenicity": strain.animal_pathogenicity,
            "plant_pathogenicity": strain.plant_pathogenicity,
            "isolation_source": strain.isolation_source,
            "country_of_origin": strain.country_of_origin,
            "isolation_date": strain.isolation_date,
            "identification": {
                "public_id": str(identification.public_id),
                "identified_on": data.identified_on.isoformat(),
                "method": identification.method,
            },
            "restrictions": [_restriction_values(r) for r in data.restrictions],
        }
        record_event(
            STRAIN_CREATED,
            Change(
                STRAIN,
                strain.public_id,
                {k: [None, v] for k, v in values.items()},
                lab_id=locked_lab.pk,
                strain_id=strain.public_id,
            ),
        )
    return strain


def strain_reclassify(
    *, access: Access, strain: Strain, taxon: Taxon, identified_on: date, method: str, reason: str
) -> Strain:
    """A new identification becomes the current one; the history keeps the old ones."""
    method = normalised(method)
    if not method:
        raise InvalidStrain("Enter how it was identified.", attr="method")
    _check_not_future(identified_on, "identified_on")
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require_role(access, strain.lab_id)
        locked = _locked_strain(strain)
        current = (
            StrainIdentification.objects.select_for_update()
            .filter(strain=locked, is_current=True)
            .select_related("taxon")
            .get()
        )
        # Off first: the partial unique index allows one current row at any moment.
        current.is_current = False
        current.save(update_fields=["is_current", "updated_at"])
        added = StrainIdentification.objects.create(
            lab_id=locked.lab_id,
            strain=locked,
            taxon=taxon,
            identified_on=identified_on,
            method=method,
            reason=reason,
            is_current=True,
        )
        old_taxon = current.taxon
        locked.taxon = taxon
        locked.save(update_fields=["taxon", "updated_at"])
        record_event(
            STRAIN_RECLASSIFIED,
            Change(
                STRAIN,
                locked.public_id,
                {
                    "taxon": [str(old_taxon.public_id), str(taxon.public_id)],
                    "identification": [str(current.public_id), str(added.public_id)],
                    "identified_on": [None, identified_on.isoformat()],
                    "method": [None, method],
                },
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
    return locked


def _check_boxes_hold(strain: Strain, risk_group: int) -> None:
    """A higher group must fit the cap of every box that holds a vial of the strain now (ADR 0009,
    the may_store gate). Caller holds the lab lock, then the strain's row; the boxes are locked
    last, in pk order. Placements take the lab lock too, so none appears meanwhile."""
    boxes = list(
        StorageUnit.objects.select_for_update()
        .filter(
            pk__in=VialPlacement.objects.filter(
                removed_at__isnull=True, vial__batch__strain=strain
            ).values("box_id")
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    caps = StorageUnit.objects.filter(pk__in=boxes).with_path_facts()
    if any(vars(box)["effective_max_risk_group"] < risk_group for box in caps):
        raise RiskGroupAboveBoxCap


def strain_set_risk_group(
    *, access: Access, strain: Strain, risk_group: int, reason: str
) -> Strain:
    """The same group again changes nothing and records nothing. A higher group is refused while
    a box holding the strain's vials does not allow it; a lower one always fits."""
    _check_risk_group(risk_group)
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require_role(access, strain.lab_id)
        locked = _locked_strain(strain)
        if locked.risk_group == risk_group:
            return locked
        if risk_group > locked.risk_group:
            _check_boxes_hold(locked, risk_group)
        old = locked.risk_group
        locked.risk_group = risk_group
        record_event(
            STRAIN_RISK_GROUP_CHANGED,
            Change(
                STRAIN,
                locked.public_id,
                {"risk_group": [old, risk_group]},
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
        locked.save(update_fields=["risk_group", "updated_at"])
    return locked


def strain_set_growth(*, access: Access, strain: Strain, growth: Growth, reason: str) -> Strain:
    """How the strain is grown (OECD BRC guidelines 2007, Microorganism domain, section 7;
    WFCC guidelines 2010, 11.1): the medium from the lab's list, the temperature as a range of
    whole degrees, the atmosphere. Replaces all four at once, each may be unknown. The same
    conditions again change nothing and record nothing. Passages already recorded keep the
    conditions they were grown under."""
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require_role(access, strain.lab_id)
        locked = _locked_strain(strain)
        before = growth_of(locked)
        after = locked_growth(growth, lab_id=locked.lab_id, current=before)
        old, new = growth_values(before), growth_values(after)
        changes = {k: [old[k], new[k]] for k in new if old[k] != new[k]}
        if not changes:
            return locked
        for column, value in growth_fields(after).items():
            setattr(locked, column, value)
        record_event(
            STRAIN_GROWTH_CHANGED,
            Change(
                STRAIN,
                locked.public_id,
                changes,
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
        locked.save(update_fields=[*growth_fields(after), "updated_at"])
    return locked


def strain_restriction_add(
    *, access: Access, strain: Strain, restriction: RestrictionInput, reason: str
) -> StrainRestriction:
    restriction = check_restriction(restriction)
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require_role(access, strain.lab_id)
        require_authorisation(lab_id=strain.lab_id, kinds=[(restriction.kind, "kind")])
        locked = _locked_strain(strain)
        added = StrainRestriction(
            lab_id=locked.lab_id, strain=locked, **_restriction_values(restriction)
        )
        _save(
            added,
            {
                ACTIVE_RESTRICTION_UNIQUE: InvalidStrain(
                    "The strain has this restriction already.", code="unique", attr="reference"
                )
            },
        )
        record_event(
            STRAIN_RESTRICTION_ADDED,
            Change(
                STRAIN,
                locked.public_id,
                {
                    "restriction": [
                        None,
                        {"public_id": str(added.public_id), **_restriction_values(added)},
                    ]
                },
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
    return added


def _locked_restriction(restriction: StrainRestriction) -> StrainRestriction:
    """The restriction locked, active. Caller holds the lab lock."""
    locked = (
        StrainRestriction.objects.select_for_update()
        .filter(pk=restriction.pk)
        .select_related("strain")
        .first()
    )
    if locked is None:
        raise NotFound
    if locked.ended_at is not None:
        raise RestrictionEnded
    return locked


def _open_proposal(restriction: StrainRestriction, named: uuid.UUID) -> RestrictionEndProposal:
    """The restriction's open proposal, locked, if it is the one the caller read."""
    proposal = (
        RestrictionEndProposal.objects.select_for_update()
        .filter(restriction=restriction, confirmed_at__isnull=True, withdrawn_at__isnull=True)
        .select_related("proposed_by")
        .first()
    )
    if proposal is None:
        raise EndNotProposed
    if proposal.public_id != named:
        raise EndProposalChanged
    return proposal


def strain_restriction_end_propose(
    *, access: Access, restriction: StrainRestriction, reason: str
) -> RestrictionEndProposal:
    """The first of two steps to end a restriction (#105, ADR 0009): someone who manages strains
    proposes it, with the reason it will end with (an annex no longer lists the agent). Nothing
    changes for the strain until a manager other than the proposer confirms it."""
    reason = _check_reason(reason)  # the proposal and the restriction's end both keep it
    with audited_atomic():
        lock_lab(restriction.lab_id)
        _require_role(access, restriction.lab_id)
        locked = _locked_restriction(restriction)
        if locked.end_proposals.filter(confirmed_at__isnull=True, withdrawn_at__isnull=True):
            raise EndProposed
        proposal = RestrictionEndProposal.objects.create(
            lab_id=locked.lab_id,
            restriction=locked,
            reason=reason,
            proposed_by=access.user,
            proposed_at=timezone.now(),
        )
        record_event(
            STRAIN_RESTRICTION_END_PROPOSED,
            Change(
                STRAIN,
                locked.strain.public_id,
                {
                    "end_proposal": [
                        None,
                        {
                            "public_id": str(proposal.public_id),
                            "restriction": str(locked.public_id),
                        },
                    ]
                },
                lab_id=locked.lab_id,
                strain_id=locked.strain.public_id,
            ),
            reason=reason,
        )
    return proposal


def strain_restriction_end_confirm(
    *, access: Access, restriction: StrainRestriction, proposal: uuid.UUID
) -> StrainRestriction:
    """The second step: a manager other than the proposer confirms the proposal they read
    (`proposal`, its public id). The restriction ends now, with the proposal's reason; the row
    stays, and the event holds both people and both times."""
    with audited_atomic():
        lock_lab(restriction.lab_id)
        _require_role(access, restriction.lab_id, Perm.CONFIRM_RESTRICTION_END)
        locked = _locked_restriction(restriction)
        proposed = _open_proposal(locked, proposal)
        if proposed.proposed_by_id == access.user.pk:
            raise ConfirmOwnEndProposal
        now = timezone.now()
        proposed.confirmed_by, proposed.confirmed_at = access.user, now
        proposed.save(update_fields=["confirmed_by", "confirmed_at", "updated_at"])
        locked.ended_at, locked.end_reason = now, proposed.reason
        record_event(
            STRAIN_RESTRICTION_ENDED,
            Change(
                STRAIN,
                locked.strain.public_id,
                {
                    "restriction": [
                        {"public_id": str(locked.public_id), **_restriction_values(locked)},
                        None,
                    ],
                    "end_proposal": [None, str(proposed.public_id)],
                    # Pseudonymous: public ids, never names (ADR 0005).
                    "proposed_by": [None, str(proposed.proposed_by.public_id)],
                    "proposed_at": [None, proposed.proposed_at.isoformat()],
                    "confirmed_by": [None, str(access.user.public_id)],
                    "confirmed_at": [None, now.isoformat()],
                },
                lab_id=locked.lab_id,
                strain_id=locked.strain.public_id,
            ),
            reason=proposed.reason,
        )
        # After the proposal: the restriction's guard asks for the confirmed proposal.
        locked.save(update_fields=["ended_at", "end_reason", "updated_at"])
    return locked


def strain_restriction_end_withdraw(
    *, access: Access, restriction: StrainRestriction, proposal: uuid.UUID, reason: str
) -> RestrictionEndProposal:
    """Anyone who manages strains withdraws the open proposal they read, with a reason (the
    agent is on the list after all). It stays with who withdrew it, when and why; the
    restriction stays active and may be proposed to end again."""
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(restriction.lab_id)
        _require_role(access, restriction.lab_id)
        locked = _locked_restriction(restriction)
        proposed = _open_proposal(locked, proposal)
        proposed.withdrawn_by, proposed.withdrawn_at = access.user, timezone.now()
        proposed.withdraw_reason = reason
        proposed.save(
            update_fields=["withdrawn_by", "withdrawn_at", "withdraw_reason", "updated_at"]
        )
        record_event(
            STRAIN_RESTRICTION_END_WITHDRAWN,
            Change(
                STRAIN,
                locked.strain.public_id,
                {"end_proposal": [str(proposed.public_id), None]},
                lab_id=locked.lab_id,
                strain_id=locked.strain.public_id,
            ),
            reason=reason,
        )
    return proposed


# Deaccession (#20).


def _check_deaccession(data: Deaccession) -> Deaccession:
    """Before any lock: the reason and the cause. The final use is checked under the lock, against
    the strain's restrictions as committed then."""
    reason = _check_reason(data.reason)
    if data.cause not in DeaccessionCause.values:
        raise InvalidStrain("Choose why the strain leaves.", attr="cause")
    return Deaccession(data.cause, reason, data.final_use)


def _regulated(strain: Strain) -> bool:
    """ADR 0009: the one definition (selectors.regulating_restrictions). Caller holds the lab
    lock, under which restrictions change."""
    return regulating_restrictions().filter(strain=strain).exists()


def _check_final_use(strain: Strain, final_use: FinalUse | None) -> None:
    """A quarantine pest states its final use; nothing else does (Regulation (EU) 2019/829,
    Annex I (h))."""
    quarantine = (
        regulating_restrictions()
        .filter(strain=strain, kind=RestrictionKind.QUARANTINE_PEST)
        .exists()
    )
    if quarantine and not final_use:
        raise InvalidStrain(
            "A quarantine pest states its final use: destruction, transfer to a collection or"
            " storage.",
            code="final_use_required",
            attr="final_use",
        )
    if not quarantine and final_use:
        raise InvalidStrain(
            "Only a quarantine pest states a final use.",
            code="final_use_not_applicable",
            attr="final_use",
        )


def _deaccession_values(data: Deaccession) -> dict[str, Any]:
    return {"cause": data.cause, "final_use": data.final_use or ""}


def _leave(
    access: Access, locked: Strain, data: Deaccession, now: datetime, *, extra: dict[str, Any]
) -> Strain:
    """The strain leaves (caller holds the lab lock and the strain's row): its open requests are
    cancelled, its vials still held are marked for destruction or, when its final use keeps the
    material, released from their requests, and the strain becomes deaccessioned. One event for
    the strain with what happened; the requests and vials record their own."""
    cancelled = distribution.requests_cancel_for_deaccession_locked(
        access=access, strain=locked, reason=data.reason
    )
    destroy = data.final_use not in KEEPS_MATERIAL
    vials = lineage.strain_vials_leave_locked(
        access=access, strain=locked, reason=f"Strain deaccessioned: {data.reason}", destroy=destroy
    )
    old = locked.status
    locked.status = StrainStatus.DEACCESSIONED
    locked.deaccessioned_at, locked.deaccessioned_by = now, access.user
    locked.deaccession_cause, locked.deaccession_reason = data.cause, data.reason
    locked.final_use = data.final_use or ""
    locked.save(
        update_fields=[
            "status",
            "deaccessioned_at",
            "deaccessioned_by",
            "deaccession_cause",
            "deaccession_reason",
            "final_use",
            "updated_at",
        ]
    )
    changes: dict[str, Any] = {
        "status": [old, StrainStatus.DEACCESSIONED],
        "cause": [None, data.cause],
        "requests_cancelled": [None, [r.label for r in cancelled]],
        ("vials_to_destroy" if destroy else "vials_released"): [None, len(vials)],
        **extra,
    }
    if data.final_use:
        changes["final_use"] = [None, data.final_use]
    record_event(
        STRAIN_DEACCESSIONED,
        Change(STRAIN, locked.public_id, changes, lab_id=locked.lab_id, strain_id=locked.public_id),
        reason=data.reason,
    )
    return locked


def strain_deaccession(*, access: Access, strain: Strain, data: Deaccession) -> Strain:
    """A strain that is not regulated leaves the collection, by one person who manages strains
    (curator and up), with the cause and the reason (#20). The strain, its number and its
    history stay; a regulated strain is proposed instead (strain_deaccession_propose)."""
    data = _check_deaccession(data)
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require_role(access, strain.lab_id)
        locked = _locked_strain(strain)
        if _regulated(locked):
            raise DeaccessionNeedsSecondPerson
        # A proposal made while the strain was regulated is settled first: confirmed, it holds
        # both people; left open, it would wait on a strain that is gone.
        if locked.deaccession_proposals.filter(
            confirmed_at__isnull=True, withdrawn_at__isnull=True
        ).exists():
            raise DeaccessionProposed
        _check_final_use(locked, data.final_use)
        return _leave(access, locked, data, timezone.now(), extra={})


def _open_deaccession(strain: Strain, named: uuid.UUID) -> StrainDeaccessionProposal:
    """The strain's open proposal, locked, if it is the one the caller read."""
    proposal = (
        StrainDeaccessionProposal.objects.select_for_update(of=("self",))
        .filter(strain=strain, confirmed_at__isnull=True, withdrawn_at__isnull=True)
        .select_related("proposed_by")
        .first()
    )
    if proposal is None:
        raise DeaccessionNotProposed
    if proposal.public_id != named:
        raise DeaccessionProposalChanged
    return proposal


def strain_deaccession_propose(
    *, access: Access, strain: Strain, data: Deaccession
) -> StrainDeaccessionProposal:
    """The first of two steps for a regulated strain (#20, ADR 0009): someone who manages strains
    proposes it with the cause, the reason and for a quarantine pest the final use. Nothing
    changes for the strain, its requests or its vials until a manager other than the proposer
    confirms it."""
    data = _check_deaccession(data)
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require_role(access, strain.lab_id)
        locked = _locked_strain(strain)
        if not _regulated(locked):
            raise DeaccessionInOneStep
        _check_final_use(locked, data.final_use)
        if locked.deaccession_proposals.filter(
            confirmed_at__isnull=True, withdrawn_at__isnull=True
        ).exists():
            raise DeaccessionProposed
        proposal = StrainDeaccessionProposal(
            lab_id=locked.lab_id,
            strain=locked,
            cause=data.cause,
            reason=data.reason,
            final_use=data.final_use or "",
            proposed_by=access.user,
            proposed_at=timezone.now(),
        )
        _save(proposal, {ONE_OPEN_DEACCESSION_PROPOSAL: DeaccessionProposed()})
        record_event(
            STRAIN_DEACCESSION_PROPOSED,
            Change(
                STRAIN,
                locked.public_id,
                {
                    "deaccession_proposal": [
                        None,
                        {"public_id": str(proposal.public_id), **_deaccession_values(data)},
                    ]
                },
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=data.reason,
        )
    return proposal


def strain_deaccession_confirm(*, access: Access, strain: Strain, proposal: uuid.UUID) -> Strain:
    """The second step: a manager other than the proposer confirms the proposal they read
    (`proposal`, its public id). The strain leaves now, with the proposal's cause, reason and
    final use; the event holds both people and both times."""
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require_role(access, strain.lab_id, Perm.CONFIRM_DEACCESSION)
        locked = _locked_strain(strain)
        proposed = _open_deaccession(locked, proposal)
        if proposed.proposed_by_id == access.user.pk:
            raise ConfirmOwnDeaccession
        data = Deaccession(
            DeaccessionCause(proposed.cause),
            proposed.reason,
            FinalUse(proposed.final_use) if proposed.final_use else None,
        )
        try:
            _check_final_use(locked, data.final_use)
        except InvalidStrain:
            raise DeaccessionProposalOutdated from None
        now = timezone.now()
        proposed.confirmed_by, proposed.confirmed_at = access.user, now
        proposed.save(update_fields=["confirmed_by", "confirmed_at", "updated_at"])
        # After the proposal: the strain's guard asks for the confirmed proposal.
        return _leave(
            access,
            locked,
            data,
            now,
            extra={
                "deaccession_proposal": [None, str(proposed.public_id)],
                # Pseudonymous: public ids, never names (ADR 0005).
                "proposed_by": [None, str(proposed.proposed_by.public_id)],
                "proposed_at": [None, proposed.proposed_at.isoformat()],
                "confirmed_by": [None, str(access.user.public_id)],
                "confirmed_at": [None, now.isoformat()],
            },
        )


def strain_deaccession_withdraw(
    *, access: Access, strain: Strain, proposal: uuid.UUID, reason: str
) -> StrainDeaccessionProposal:
    """Anyone who manages strains withdraws the open proposal they read, with a reason (the
    strain grew after all). It stays with who withdrew it, when and why; the strain stays in
    the collection and may be proposed again."""
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require_role(access, strain.lab_id)
        locked = _locked_strain(strain)
        proposed = _open_deaccession(locked, proposal)
        proposed.withdrawn_by, proposed.withdrawn_at = access.user, timezone.now()
        proposed.withdraw_reason = reason
        proposed.save(
            update_fields=["withdrawn_by", "withdrawn_at", "withdraw_reason", "updated_at"]
        )
        record_event(
            STRAIN_DEACCESSION_WITHDRAWN,
            Change(
                STRAIN,
                locked.public_id,
                {"deaccession_proposal": [str(proposed.public_id), None]},
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
    return proposed

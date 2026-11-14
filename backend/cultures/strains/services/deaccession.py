"""A strain leaves the collection (#20): in one step when it is not regulated, in two steps by
two people when it is (the steps in strains.proposals).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    STRAIN_DEACCESSION_PROPOSED,
    STRAIN_DEACCESSION_WITHDRAWN,
    STRAIN_DEACCESSIONED,
)
from cultures.biosafety.models import RestrictionKind
from cultures.core.constraints import save_arbitrated
from cultures.core.exceptions import Conflict, Forbidden, RuleViolation
from cultures.distribution import services as distribution
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab, require_committed
from cultures.labs.permissions import Perm
from cultures.lineage import services as lineage

from ..models import (
    KEEPS_MATERIAL,
    ONE_OPEN_DEACCESSION_PROPOSAL,
    DeaccessionCause,
    FinalUse,
    Strain,
    StrainDeaccessionProposal,
    StrainStatus,
)
from ..proposals import check_not_own, confirm, has_open, open_proposal, withdraw
from ..selectors import regulating_restrictions
from ._shared import STRAIN, InvalidStrain, _check_reason, _locked_strain


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
        require_committed(access, strain.lab_id, Perm.MANAGE_STRAINS)
        locked = _locked_strain(strain)
        if _regulated(locked):
            raise DeaccessionNeedsSecondPerson
        # A proposal made while the strain was regulated is settled first: confirmed, it holds
        # both people; left open, it would wait on a strain that is gone.
        if has_open(locked.deaccession_proposals.all()):
            raise DeaccessionProposed
        _check_final_use(locked, data.final_use)
        return _leave(access, locked, data, timezone.now(), extra={})


def _open_deaccession(strain: Strain, named: uuid.UUID) -> StrainDeaccessionProposal:
    """The strain's open proposal, locked, if it is the one the caller read."""
    return open_proposal(
        StrainDeaccessionProposal.objects.select_for_update(of=("self",))
        .filter(strain=strain)
        .select_related("proposed_by"),
        named,
        missing=DeaccessionNotProposed(),
        changed=DeaccessionProposalChanged(),
    )


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
        require_committed(access, strain.lab_id, Perm.MANAGE_STRAINS)
        locked = _locked_strain(strain)
        if not _regulated(locked):
            raise DeaccessionInOneStep
        _check_final_use(locked, data.final_use)
        if has_open(locked.deaccession_proposals.all()):
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
        save_arbitrated(proposal, {ONE_OPEN_DEACCESSION_PROPOSAL: DeaccessionProposed()})
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
        require_committed(access, strain.lab_id, Perm.CONFIRM_DEACCESSION)
        locked = _locked_strain(strain)
        proposed = _open_deaccession(locked, proposal)
        check_not_own(proposed, access, ConfirmOwnDeaccession())
        data = Deaccession(
            DeaccessionCause(proposed.cause),
            proposed.reason,
            FinalUse(proposed.final_use) if proposed.final_use else None,
        )
        try:
            _check_final_use(locked, data.final_use)
        except InvalidStrain:
            raise DeaccessionProposalOutdated from None
        now, people = confirm(proposed, access, "strains_deaccessionproposal_confirmed")
        # After the proposal: the strain's guard asks for the confirmed proposal.
        return _leave(
            access,
            locked,
            data,
            now,
            extra={
                "deaccession_proposal": [None, str(proposed.public_id)],
                **people,
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
        require_committed(access, strain.lab_id, Perm.MANAGE_STRAINS)
        locked = _locked_strain(strain)
        proposed = _open_deaccession(locked, proposal)
        withdraw(proposed, access, reason)
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

"""A strain's risk group: set by one person, lowered in two steps by two people (#174, the
steps in strains.proposals).
"""

import uuid
from datetime import datetime
from typing import Any

from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    STRAIN_RISK_GROUP_CHANGED,
    STRAIN_RISK_GROUP_LOWER_PROPOSED,
    STRAIN_RISK_GROUP_LOWER_WITHDRAWN,
)
from cultures.biosafety.models import RegulatoryListEntry
from cultures.core.constraints import save_arbitrated
from cultures.core.exceptions import Conflict, DomainError, Forbidden, RuleViolation
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab, require_committed
from cultures.labs.permissions import Perm
from cultures.lineage.models import VialPlacement
from cultures.storage.models import StorageUnit

from ..models import (
    ONE_OPEN_RISK_GROUP_PROPOSAL,
    RiskGroupProposal,
    Strain,
)
from ..proposals import check_not_own, confirm, has_open, open_proposal, withdraw
from ._shared import (
    STRAIN,
    _check_basis,
    _check_basis_entry,
    _check_reason,
    _check_risk_group,
    _entry_code,
    _locked_strain,
)


class RiskGroupAboveBoxCap(DomainError):
    """A field error on the risk group. Names no box: a regulated strain's place stays masked."""

    default_code = "risk_group_above_box_cap"
    default_detail = "A box holding this strain's vials does not allow this risk group."

    def __init__(self, detail: str | None = None, *, attr: str | None = "risk_group") -> None:
        super().__init__(detail, attr=attr)


class RiskGroupStepTooBig(DomainError):
    """A field error on the risk group: a raise goes one step at a time (#174, our own rule)."""

    default_code = "risk_group_step_too_big"
    default_detail = "A risk group rises one step at a time: raise it by one, then again."

    def __init__(self, detail: str | None = None, *, attr: str | None = "risk_group") -> None:
        super().__init__(detail, attr=attr)


class RiskGroupNeedsSecondPerson(RuleViolation):
    """ADR 0009 (#174): a lower risk group relaxes the rules the higher one brings."""

    default_code = "risk_group_second_person_required"
    default_detail = "A lower risk group is proposed, and a manager other than you confirms it."


class RiskGroupNotLower(RuleViolation):
    """Only a lowering is proposed: a raise and the same group are one person's."""

    default_code = "risk_group_not_lower"
    default_detail = "This is not a lower risk group: change it in one step instead."


class RiskGroupProposed(Conflict):
    """One open proposal per strain: the second one waits for the first to be settled."""

    default_code = "risk_group_proposed"
    default_detail = "Someone has proposed to lower this strain's risk group already."


class RiskGroupNotProposed(Conflict):
    default_code = "risk_group_not_proposed"
    default_detail = "Nobody has proposed to lower this risk group, or the proposal was settled."


class RiskGroupProposalChanged(Conflict):
    """The confirmation names the proposal the manager read; another one is open now."""

    default_code = "risk_group_proposal_changed"
    default_detail = "The proposal changed meanwhile. Read it again before you confirm."


class RiskGroupProposalOutdated(Conflict):
    """The strain no longer has the group the proposal read its basis against."""

    default_code = "risk_group_proposal_outdated"
    default_detail = (
        "The strain's risk group changed since the proposal: withdraw it and propose again."
    )


class ConfirmOwnRiskGroup(Forbidden):
    """ADR 0009 (#174): nobody confirms the lowering they proposed."""

    default_code = "confirm_own_risk_group"
    default_detail = "You proposed this risk group: a different manager confirms it."


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


def _risk_group_fields(
    locked: Strain,
    risk_group: int,
    basis: str,
    now: datetime,
    entry: RegulatoryListEntry | None = None,
) -> dict[str, Any]:
    """The strain's new group with its basis, the list entry the basis rests on and the time of
    the change, and the changes the event records. The time moves forward with every change,
    which is what ties a lowering to one confirmed proposal (migration 0014)."""
    old, old_basis = locked.risk_group, locked.risk_group_basis
    # One query, and only for a strain whose group already rested on an entry: the locked row
    # holds the id, and an event names an entry by its code in its list, never by a row id.
    old_entry = (
        RegulatoryListEntry.objects.filter(pk=locked.risk_group_entry_id)
        .values_list("code", flat=True)
        .first()
        if locked.risk_group_entry_id is not None
        else None
    )
    locked.risk_group = risk_group
    locked.risk_group_basis = basis
    locked.risk_group_set_at = now
    locked.risk_group_entry = entry
    return {
        "risk_group": [old, risk_group],
        "basis": [old_basis or None, basis],
        "basis_entry": [old_entry, _entry_code(entry)],
    }


RISK_GROUP_FIELDS = [
    "risk_group",
    "risk_group_basis",
    "risk_group_set_at",
    "risk_group_entry",
    "updated_at",
]


def strain_set_risk_group(
    *,
    access: Access,
    strain: Strain,
    risk_group: int,
    basis: str,
    reason: str,
    basis_entry: RegulatoryListEntry | None = None,
) -> Strain:
    """A raise, or the same group again, by one person who manages strains, with the basis and
    the reason (#174). The basis may point at the entry of annex 7 of government order 361/2007
    Sb. it was read in (#169). The same group changes nothing and records nothing. A raise goes
    one step at a time and is refused while a box holding the strain's vials does not allow it.
    A lower group is proposed instead (strain_risk_group_lower_propose)."""
    _check_risk_group(risk_group)
    basis = _check_basis(basis)
    _check_basis_entry(basis_entry, risk_group)
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(strain.lab_id)
        require_committed(access, strain.lab_id, Perm.MANAGE_STRAINS)
        locked = _locked_strain(strain)
        if locked.risk_group == risk_group:
            return locked
        if risk_group < locked.risk_group:
            raise RiskGroupNeedsSecondPerson
        if risk_group > locked.risk_group + 1:
            raise RiskGroupStepTooBig
        _check_boxes_hold(locked, risk_group)
        changes = _risk_group_fields(locked, risk_group, basis, timezone.now(), basis_entry)
        record_event(
            STRAIN_RISK_GROUP_CHANGED,
            Change(
                STRAIN,
                locked.public_id,
                changes,
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
        locked.save(update_fields=RISK_GROUP_FIELDS)
    return locked


def _open_risk_group(strain: Strain, named: uuid.UUID) -> RiskGroupProposal:
    """The strain's open proposal to lower its group, locked, if it is the one the caller read."""
    return open_proposal(
        RiskGroupProposal.objects.select_for_update(of=("self",))
        .filter(strain=strain)
        # basis_entry is nullable, hence of=("self",) above: the row of the proposal is locked
        # and the entry, which nothing ever changes, is not.
        .select_related("proposed_by", "basis_entry"),
        named,
        missing=RiskGroupNotProposed(),
        changed=RiskGroupProposalChanged(),
    )


def strain_risk_group_lower_propose(
    *,
    access: Access,
    strain: Strain,
    risk_group: int,
    basis: str,
    reason: str,
    basis_entry: RegulatoryListEntry | None = None,
) -> RiskGroupProposal:
    """The first of two steps to lower a risk group (#174, ADR 0009): someone who manages
    strains proposes it, with the basis the lower group rests on, the list entry that basis was
    read in where there is one (#169), and the reason. Nothing changes for the strain until a
    manager other than the proposer confirms it, so every rule that reads the risk group still
    reads the higher one."""
    _check_risk_group(risk_group)
    basis = _check_basis(basis)
    _check_basis_entry(basis_entry, risk_group)
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(strain.lab_id)
        require_committed(access, strain.lab_id, Perm.MANAGE_STRAINS)
        locked = _locked_strain(strain)
        if risk_group >= locked.risk_group:
            raise RiskGroupNotLower
        if has_open(locked.risk_group_proposals.all()):
            raise RiskGroupProposed
        proposal = RiskGroupProposal(
            lab_id=locked.lab_id,
            strain=locked,
            risk_group=risk_group,
            from_risk_group=locked.risk_group,
            basis=basis,
            basis_entry=basis_entry,
            reason=reason,
            proposed_by=access.user,
            proposed_at=timezone.now(),
        )
        save_arbitrated(proposal, {ONE_OPEN_RISK_GROUP_PROPOSAL: RiskGroupProposed()})
        record_event(
            STRAIN_RISK_GROUP_LOWER_PROPOSED,
            Change(
                STRAIN,
                locked.public_id,
                {
                    "risk_group_proposal": [
                        None,
                        {
                            "public_id": str(proposal.public_id),
                            "risk_group": risk_group,
                            "from_risk_group": locked.risk_group,
                            "basis": basis,
                            "basis_entry": _entry_code(basis_entry),
                        },
                    ]
                },
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
    return proposal


def strain_risk_group_lower_confirm(
    *, access: Access, strain: Strain, proposal: uuid.UUID
) -> Strain:
    """The second step: a manager other than the proposer confirms the proposal they read
    (`proposal`, its public id). The group drops now, with the proposal's basis; the event holds
    both people and both times. A strain whose group changed since the proposal is refused: the
    basis was read against the group the proposal names."""
    with audited_atomic():
        lock_lab(strain.lab_id)
        require_committed(access, strain.lab_id, Perm.CONFIRM_RISK_GROUP)
        locked = _locked_strain(strain)
        proposed = _open_risk_group(locked, proposal)
        check_not_own(proposed, access, ConfirmOwnRiskGroup())
        if proposed.from_risk_group != locked.risk_group:
            raise RiskGroupProposalOutdated
        now, people = confirm(proposed, access, "strains_riskgroupproposal_confirmed")
        changes = _risk_group_fields(
            locked, proposed.risk_group, proposed.basis, now, proposed.basis_entry
        )
        record_event(
            STRAIN_RISK_GROUP_CHANGED,
            Change(
                STRAIN,
                locked.public_id,
                {
                    **changes,
                    "risk_group_proposal": [None, str(proposed.public_id)],
                    **people,
                },
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=proposed.reason,
        )
        # After the proposal: the strain's guard asks for the confirmed proposal.
        locked.save(update_fields=RISK_GROUP_FIELDS)
    return locked


def strain_risk_group_lower_withdraw(
    *, access: Access, strain: Strain, proposal: uuid.UUID, reason: str
) -> RiskGroupProposal:
    """Anyone who manages strains withdraws the open proposal they read, with a reason (the list
    entry held after all). It stays with who withdrew it, when and why; the strain keeps its
    group and may be proposed again."""
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(strain.lab_id)
        require_committed(access, strain.lab_id, Perm.MANAGE_STRAINS)
        locked = _locked_strain(strain)
        proposed = _open_risk_group(locked, proposal)
        withdraw(proposed, access, reason)
        record_event(
            STRAIN_RISK_GROUP_LOWER_WITHDRAWN,
            Change(
                STRAIN,
                locked.public_id,
                {"risk_group_proposal": [str(proposed.public_id), None]},
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
    return proposed

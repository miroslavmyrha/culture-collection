"""A strain's restrictions: added by one person, ended in two steps by two people (#105, the
steps in strains.proposals).
"""

import uuid

from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    STRAIN_RESTRICTION_ADDED,
    STRAIN_RESTRICTION_END_PROPOSED,
    STRAIN_RESTRICTION_END_WITHDRAWN,
    STRAIN_RESTRICTION_ENDED,
)
from cultures.biosafety import selectors as biosafety_lists
from cultures.biosafety.models import RestrictionKind
from cultures.biosafety.policy import require_authorisation
from cultures.core.constraints import save_arbitrated
from cultures.core.exceptions import Conflict, Forbidden, NotFound
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab, require_committed
from cultures.labs.permissions import Perm

from ..models import (
    ACTIVE_RESTRICTION_UNIQUE,
    RestrictionEndProposal,
    Strain,
    StrainRestriction,
)
from ..proposals import check_not_own, confirm, has_open, open_proposal, withdraw
from ._shared import (
    STRAIN,
    InvalidStrain,
    RestrictionHeldByDualUse,
    RestrictionInput,
    _active_kinds,
    _check_reason,
    _entry_of,
    _locked_strain,
    _require_cz_agent,
    _restriction_values,
    check_restriction,
)


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


def strain_restriction_add(
    *, access: Access, strain: Strain, restriction: RestrictionInput, reason: str
) -> StrainRestriction:
    restriction = check_restriction(restriction)
    with audited_atomic():
        lock_lab(strain.lab_id)
        require_committed(access, strain.lab_id, Perm.MANAGE_STRAINS)
        require_authorisation(lab_id=strain.lab_id, kinds=[(restriction.kind, "kind")])
        locked = _locked_strain(strain)
        entry = _entry_of(restriction)
        _require_cz_agent([entry], _active_kinds(locked) | {restriction.kind})
        added = StrainRestriction(
            lab_id=locked.lab_id,
            strain=locked,
            list_entry=entry,
            **_restriction_values(restriction),
        )
        save_arbitrated(
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


def _check_end_allowed(locked: StrainRestriction) -> None:
    """#169, the last box, the other way round: a VRAT or RAT restriction does not end while an
    active dual-use restriction of the same strain names an entry of 1C351.a, 1C351.c, 1C351.e
    or 1C354 that decree 474/2002 Sb. lists as that agent. The deferred trigger of migration
    0016 asks the same at commit. Caller holds the lab lock and the restriction's row."""
    if locked.kind not in (RestrictionKind.CZ_VRAT, RestrictionKind.CZ_RAT):
        return
    dual_use = (
        StrainRestriction.objects.filter(
            strain_id=locked.strain_id,
            ended_at__isnull=True,
            kind=RestrictionKind.DUAL_USE,
            list_entry__isnull=False,
        )
        .select_related("list_entry")
        .order_by("pk")
    )
    for other in dual_use:
        entry = other.list_entry
        if entry is None:
            continue
        counterpart = biosafety_lists.also_a_cz_agent(entry)
        if counterpart is not None and counterpart.restriction_kind == locked.kind:
            raise RestrictionHeldByDualUse


def _open_proposal(restriction: StrainRestriction, named: uuid.UUID) -> RestrictionEndProposal:
    """The restriction's open proposal, locked, if it is the one the caller read."""
    return open_proposal(
        RestrictionEndProposal.objects.select_for_update()
        .filter(restriction=restriction)
        .select_related("proposed_by"),
        named,
        missing=EndNotProposed(),
        changed=EndProposalChanged(),
    )


def strain_restriction_end_propose(
    *, access: Access, restriction: StrainRestriction, reason: str
) -> RestrictionEndProposal:
    """The first of two steps to end a restriction (#105, ADR 0009): someone who manages strains
    proposes it, with the reason it will end with (an annex no longer lists the agent). Nothing
    changes for the strain until a manager other than the proposer confirms it."""
    reason = _check_reason(reason)  # the proposal and the restriction's end both keep it
    with audited_atomic():
        lock_lab(restriction.lab_id)
        require_committed(access, restriction.lab_id, Perm.MANAGE_STRAINS)
        locked = _locked_restriction(restriction)
        _check_end_allowed(locked)
        if has_open(locked.end_proposals.all()):
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
        require_committed(access, restriction.lab_id, Perm.CONFIRM_RESTRICTION_END)
        locked = _locked_restriction(restriction)
        _check_end_allowed(locked)
        proposed = _open_proposal(locked, proposal)
        check_not_own(proposed, access, ConfirmOwnEndProposal())
        now, people = confirm(proposed, access, "strains_endproposal_confirmed")
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
                    **people,
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
        require_committed(access, restriction.lab_id, Perm.MANAGE_STRAINS)
        locked = _locked_restriction(restriction)
        proposed = _open_proposal(locked, proposal)
        withdraw(proposed, access, reason)
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

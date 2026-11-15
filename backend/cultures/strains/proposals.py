"""The two-person flow every strain proposal shares (#234, ADR 0009).

Lowering a risk group, ending a restriction and deaccessioning a regulated strain each go in two
steps: someone who manages strains proposes, a manager other than the proposer confirms the
proposal they read, and anyone who manages strains may withdraw it with a reason. The flows differ
in what they check and what they change; the steps of a proposal itself are here, once.
"""

import uuid
from datetime import datetime
from typing import Literal

from django.db import connection
from django.db.models import QuerySet
from django.utils import timezone

from cultures.labs.access import Access

from .models import RestrictionEndProposal, RiskGroupProposal, StrainDeaccessionProposal

# A proposal neither confirmed nor withdrawn. A target has at most one (a unique constraint each).
OPEN = {"confirmed_at__isnull": True, "withdrawn_at__isnull": True}

Trigger = Literal[
    "strains_endproposal_confirmed",
    "strains_deaccessionproposal_confirmed",
    "strains_riskgroupproposal_confirmed",
]


def has_open[P: (RiskGroupProposal, RestrictionEndProposal, StrainDeaccessionProposal)](
    proposals: QuerySet[P],
) -> bool:
    return proposals.filter(**OPEN).exists()


def open_proposal[P: (RiskGroupProposal, RestrictionEndProposal, StrainDeaccessionProposal)](
    proposals: QuerySet[P], named: uuid.UUID, *, missing: Exception, changed: Exception
) -> P:
    """The open proposal among `proposals` (the caller's query, which locks it), if it is the one
    the caller read: `missing` when there is none, `changed` when another one replaced it."""
    found = proposals.filter(**OPEN).first()
    if found is None:
        raise missing
    if found.public_id != named:
        raise changed
    return found


def check_not_own[P: (RiskGroupProposal, RestrictionEndProposal, StrainDeaccessionProposal)](
    proposal: P, access: Access, own: Exception
) -> None:
    """Nobody confirms their own proposal: the second person is the point."""
    if proposal.proposed_by_id == access.user.pk:
        raise own


def defer_outcome_check(trigger: Trigger) -> None:
    """A confirmed proposal holds its outcome at commit (strains 0010 and 0014), and the outcome
    is written after the confirmation, which the guards ask for first: the check waits for the
    commit, also in a session that set its constraints immediate."""
    with connection.cursor() as cursor:
        cursor.execute(f"SET CONSTRAINTS {trigger} DEFERRED")


def confirm[P: (RiskGroupProposal, RestrictionEndProposal, StrainDeaccessionProposal)](
    proposal: P, access: Access, trigger: Trigger
) -> tuple[datetime, dict[str, list[str | None]]]:
    """Record the confirmation, now, and return the time with the fields the confirming event
    holds: both people, by public id, never by name (ADR 0005), and both times."""
    now = timezone.now()
    defer_outcome_check(trigger)
    proposal.confirmed_by, proposal.confirmed_at = access.user, now
    proposal.save(update_fields=["confirmed_by", "confirmed_at", "updated_at"])
    people: dict[str, list[str | None]] = {
        "proposed_by": [None, str(proposal.proposed_by.public_id)],
        "proposed_at": [None, proposal.proposed_at.isoformat()],
        "confirmed_by": [None, str(access.user.public_id)],
        "confirmed_at": [None, now.isoformat()],
    }
    return now, people


def withdraw[P: (RiskGroupProposal, RestrictionEndProposal, StrainDeaccessionProposal)](
    proposal: P, access: Access, reason: str
) -> None:
    """Record who withdrew the proposal, when and why. It stays, and the target may be proposed
    again."""
    proposal.withdrawn_by, proposal.withdrawn_at = access.user, timezone.now()
    proposal.withdraw_reason = reason
    proposal.save(update_fields=["withdrawn_by", "withdrawn_at", "withdraw_reason", "updated_at"])

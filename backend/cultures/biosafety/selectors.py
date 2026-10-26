"""Reads of the lab's permits. Every one takes the access object, so the lab scope is part of
the signature."""

from datetime import date, timedelta
from enum import StrEnum

from django.db.models import (
    Case,
    CharField,
    DateField,
    F,
    IntegerField,
    Q,
    QuerySet,
    Value,
    When,
)
from django.db.models.functions import Cast, Least

from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm

from .models import LabAuthorisation
from .policy import EXPIRES_SOON_DAYS


class Standing(StrEnum):
    """Where a permit stands on a day, first match wins (policy.valid_on is the rule)."""

    ENDED = "ended"  # ended_on reached: revoked, surrendered or entered in error
    EXPIRED = "expired"  # the last valid day passed
    NOT_YET_VALID = "not_yet_valid"  # valid_from still ahead
    EXPIRES_SOON = "expires_soon"  # valid, its last valid day within EXPIRES_SOON_DAYS
    VALID = "valid"


# The screen's order: what a manager must act on first, then what holds, then the history.
_RANK = {
    Standing.EXPIRES_SOON: 0,
    Standing.VALID: 1,
    Standing.NOT_YET_VALID: 2,
    Standing.EXPIRED: 3,
    Standing.ENDED: 3,
}


def permit_list(*, access: Access, lab: Lab, today: date) -> QuerySet[LabAuthorisation]:
    """Every permit of one lab, ended ones included, each with its `standing` on `today` (a
    Czech day, policy.permit_today) and its `last_valid_day` (the expiry, or the day before an
    early end, whichever comes first; empty when neither is set). Empty unless the user may
    read the lab's permits.

    Order: expiring soon, then valid, both by the last valid day (none stated last); then not
    yet valid by start; then expired and ended, the most recent first.
    """
    horizon = today + timedelta(days=EXPIRES_SOON_DAYS)
    # ended_on is the first invalid day, so the day before it is the last valid one.
    day_before_end = Cast(F("ended_on") - timedelta(days=1), DateField())
    standing = Case(
        When(Q(ended_on__lte=today), then=Value(Standing.ENDED.value)),
        When(Q(expires_on__lt=today), then=Value(Standing.EXPIRED.value)),
        When(Q(valid_from__gt=today), then=Value(Standing.NOT_YET_VALID.value)),
        When(
            Q(expires_on__lte=horizon) | Q(ended_on__lte=horizon + timedelta(days=1)),
            then=Value(Standing.EXPIRES_SOON.value),
        ),
        default=Value(Standing.VALID.value),
        output_field=CharField(),
    )
    rank = Case(
        *(When(standing=value.value, then=Value(n)) for value, n in _RANK.items()),
        output_field=IntegerField(),
    )
    current = Q(rank__lte=1)
    return (
        LabAuthorisation.objects.for_access(access, Perm.VIEW_LAB_PERMITS)
        .filter(lab=lab)
        # PostgreSQL's LEAST skips NULLs: either date alone, or NULL when both are.
        .annotate(
            standing=standing,
            last_valid_day=Least("expires_on", day_before_end, output_field=DateField()),
        )
        .annotate(rank=rank)
        .order_by(
            "rank",
            Case(When(current, then=F("last_valid_day"))).asc(nulls_last=True),
            Case(When(rank=2, then=F("valid_from"))).asc(),
            Case(When(rank=3, then=F("last_valid_day"))).desc(nulls_last=True),
            "kind",
            "pk",
        )
    )

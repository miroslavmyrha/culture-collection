"""Which restriction kinds a lab may hold today (ADR 0009, Lab authorisation).

A cz_vrat or quarantine_pest strain enters a lab only while the lab holds a
valid authorisation of that kind. Valid on a day D: valid_from <= D, D <=
expires_on when the permit states an expiry, and D < ended_on when it ended
early. Days are Czech calendar days: the permits are issued by Czech
authorities and state their dates in local time, so 00:30 on the day after the
expiry in Prague is already after it, while UTC still says the day before.
"""

from collections.abc import Iterable
from datetime import date
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from cultures.core.exceptions import RuleViolation

from .models import AuthorisationKind, LabAuthorisation, RestrictionKind

PERMIT_TIME_ZONE = ZoneInfo("Europe/Prague")
NEEDS_PERMIT = frozenset(AuthorisationKind.values)

_WHAT = {
    AuthorisationKind.CZ_VRAT: "SÚJB permit for highly risky agents (VRAT)",
    AuthorisationKind.QUARANTINE_PEST: "ÚKZÚZ permit for quarantine pests",
}


class AuthorisationRequired(RuleViolation):
    default_code = "lab_authorisation_required"
    default_detail = "The lab holds no valid permit for this restriction."

    def __init__(self, kind: AuthorisationKind | None = None, *, attr: str | None = None) -> None:
        self.kind = kind
        detail = None if kind is None else f"The lab holds no valid {_WHAT[kind]} today."
        super().__init__(detail, attr=attr)


def permit_today() -> date:
    return timezone.now().astimezone(PERMIT_TIME_ZONE).date()


def valid_on(day: date) -> Q:
    return (
        Q(valid_from__lte=day)
        & (Q(expires_on__isnull=True) | Q(expires_on__gte=day))
        & (Q(ended_on__isnull=True) | Q(ended_on__gt=day))
    )


def require_authorisation(*, lab_id: int, kinds: Iterable[tuple[RestrictionKind, str]]) -> None:
    """Refuse the first restriction whose kind needs a permit the lab does not hold today.

    `kinds` pairs each restriction kind with the input field it came from, for the error.
    Caller holds the lab lock (labs.locks.lock_lab), so no authorisation of the lab is
    added or ended between this read and the caller's commit.
    """
    today = permit_today()
    for kind, attr in kinds:
        if kind not in NEEDS_PERMIT:
            continue
        held = LabAuthorisation.objects.filter(valid_on(today), lab_id=lab_id, kind=kind)
        if not held.exists():
            raise AuthorisationRequired(AuthorisationKind(kind), attr=attr)

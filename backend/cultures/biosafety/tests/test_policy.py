"""A cz_vrat or quarantine_pest strain needs a permit of that kind, valid today, in its own lab."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from cultures.biosafety.models import AuthorisationKind, LabAuthorisation, RestrictionKind
from cultures.biosafety.policy import AuthorisationRequired, permit_today, require_authorisation
from cultures.labs.models import Lab

from .support import make_permit

pytestmark = pytest.mark.django_db
VRAT = [(RestrictionKind.CZ_VRAT, "restrictions.0.kind")]


def held(lab: Lab, kind: RestrictionKind = RestrictionKind.CZ_VRAT) -> bool:
    try:
        require_authorisation(lab_id=lab.pk, kinds=[(kind, "kind")])
    except AuthorisationRequired:
        return False
    return True


@pytest.fixture(autouse=True)
def midsummer() -> object:
    with time_machine.travel(datetime(2026, 6, 15, 10, tzinfo=UTC), tick=False) as traveller:
        yield traveller


def test_a_valid_permit_of_the_kind_lets_the_strain_in(lab: Lab) -> None:
    make_permit(lab)
    assert held(lab)


def test_no_permit_refuses_with_the_field_and_the_kind(lab: Lab) -> None:
    with pytest.raises(AuthorisationRequired) as refused:
        require_authorisation(lab_id=lab.pk, kinds=VRAT)
    assert (refused.value.code, refused.value.attr, refused.value.kind) == (
        "lab_authorisation_required",
        "restrictions.0.kind",
        AuthorisationKind.CZ_VRAT,
    )
    assert refused.value.status_code == 422
    assert "SÚJB" in refused.value.detail


def test_a_permit_of_another_kind_does_not_count(lab: Lab) -> None:
    make_permit(lab, AuthorisationKind.QUARANTINE_PEST)
    assert not held(lab, RestrictionKind.CZ_VRAT)
    assert held(lab, RestrictionKind.QUARANTINE_PEST)


def test_a_permit_of_another_lab_does_not_count(lab: Lab, other_lab: Lab) -> None:
    make_permit(other_lab)
    assert not held(lab)


@pytest.mark.parametrize(
    ("fields", "valid"),
    [
        ({"expires_on": date(2026, 6, 14)}, False),  # expired yesterday
        ({"expires_on": date(2026, 6, 15)}, True),  # its last day
        ({"expires_on": None}, True),  # no expiry stated
        ({"valid_from": date(2026, 6, 16)}, False),  # not yet
        ({"valid_from": date(2026, 6, 15)}, True),  # its first day
        ({"ended_on": date(2026, 6, 15), "end_reason": "revoked"}, False),  # ended today
        ({"ended_on": date(2026, 6, 16), "end_reason": "surrendered"}, True),  # ends tomorrow
    ],
)
def test_validity_follows_the_dates(lab: Lab, fields: dict[str, Any], valid: bool) -> None:
    make_permit(lab, **fields)
    assert held(lab) is valid


def test_an_expired_permit_and_a_renewal_hold_together(lab: Lab) -> None:
    make_permit(
        lab, permit_reference="old", valid_from=date(2025, 1, 1), expires_on=date(2025, 12, 31)
    )
    assert not held(lab)
    make_permit(lab, permit_reference="new", valid_from=date(2026, 1, 1), expires_on=None)
    assert held(lab)


def test_kinds_without_a_permit_need_none(lab: Lab) -> None:
    for kind in (RestrictionKind.CZ_RAT, RestrictionKind.DUAL_USE, RestrictionKind.GMO):
        assert held(lab, kind)
    assert not LabAuthorisation.objects.exists()


def test_the_day_is_the_day_in_prague(lab: Lab) -> None:
    """22:30 UTC on the expiry day is 00:30 the next day in Prague: the permit has expired."""
    make_permit(lab, expires_on=date(2026, 6, 15))
    with time_machine.travel(datetime(2026, 6, 15, 21, 59, tzinfo=UTC), tick=False):
        assert permit_today() == date(2026, 6, 15)
        assert held(lab)
    with time_machine.travel(datetime(2026, 6, 15, 22, 30, tzinfo=UTC), tick=False):
        assert permit_today() == date(2026, 6, 16)
        assert not held(lab)

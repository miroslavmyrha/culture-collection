"""The database refuses a permit row that cannot be true, also when the services are skipped."""

from datetime import date
from typing import Any

import pytest
from django.db import IntegrityError, transaction

from cultures.biosafety.models import AuthorisationKind, Issuer, LabAuthorisation
from cultures.labs.models import Lab

from .support import make_permit

pytestmark = pytest.mark.django_db


def refused(constraint: str) -> Any:
    return pytest.raises(IntegrityError, match=constraint)


@pytest.mark.parametrize(
    ("kind", "issuer"),
    [
        (AuthorisationKind.CZ_VRAT, Issuer.UKZUZ),
        (AuthorisationKind.QUARANTINE_PEST, Issuer.SUJB),
        ("cz_rat", Issuer.SUJB),  # a RAT needs a notice, not a permit: no row for it
        ("gmo", Issuer.SUJB),
    ],
)
def test_each_kind_has_its_issuer_and_no_other_kind_is_a_permit(
    lab: Lab, kind: str, issuer: str
) -> None:
    with refused("biosafety_labauthorisation_kind_issuer"), transaction.atomic():
        make_permit(
            lab, AuthorisationKind.CZ_VRAT, issuer=issuer, permit_reference=f"{kind}-1"
        ).__class__.objects.filter(permit_reference=f"{kind}-1").update(kind=kind)


@pytest.mark.parametrize("reference", ["", " SÚJB/1", "SÚJB/1 "])
def test_the_reference_is_trimmed_and_not_blank(lab: Lab, reference: str) -> None:
    with refused("biosafety_labauthorisation_reference_trimmed"), transaction.atomic():
        make_permit(lab, permit_reference=reference)


def test_the_expiry_is_not_before_the_start(lab: Lab) -> None:
    with refused("biosafety_labauthorisation_expires_after_start"), transaction.atomic():
        make_permit(lab, expires_on=date(2025, 12, 31))
    make_permit(lab, permit_reference="one day", expires_on=date(2026, 1, 1))


def test_the_end_is_not_before_the_start(lab: Lab) -> None:
    with refused("biosafety_labauthorisation_ends_after_start"), transaction.atomic():
        make_permit(lab, ended_on=date(2025, 6, 1), end_reason="entered in error")


@pytest.mark.parametrize(
    ("ended_on", "reason"), [(date(2026, 6, 1), ""), (date(2026, 6, 1), "  "), (None, "revoked")]
)
def test_an_end_date_comes_with_a_reason_and_only_then(
    lab: Lab, ended_on: date | None, reason: str
) -> None:
    with refused("biosafety_labauthorisation_end_has_reason"), transaction.atomic():
        make_permit(lab, ended_on=ended_on, end_reason=reason)


def test_a_permit_is_recorded_once_per_lab_and_kind(lab: Lab, other_lab: Lab) -> None:
    make_permit(lab)
    with refused("biosafety_labauthorisation_lab_kind_reference_uniq"), transaction.atomic():
        make_permit(lab)
    make_permit(other_lab)
    make_permit(lab, AuthorisationKind.QUARANTINE_PEST)
    assert LabAuthorisation.objects.count() == 3

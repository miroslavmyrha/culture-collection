"""The database refuses bad labs and memberships, also when a service or an import is skipped."""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.users.models import User

from .conftest import make_lab, membership

pytestmark = pytest.mark.django_db


def test_one_membership_per_user_and_lab(lab: Lab, viewer: User) -> None:
    with pytest.raises(IntegrityError, match="labs_membership_user_lab_uniq"), transaction.atomic():
        Membership.objects.create(user=viewer, lab=lab, role=Role.CURATOR)


def test_the_same_user_may_belong_to_two_labs(lab: Lab, other_lab: Lab, viewer: User) -> None:
    Membership.objects.create(user=viewer, lab=other_lab, role=Role.MANAGER)
    assert Membership.objects.filter(user=viewer).count() == 2


def test_an_unknown_role_is_refused(lab: Lab, viewer: User) -> None:
    with pytest.raises(IntegrityError, match="labs_membership_role_valid"), transaction.atomic():
        Membership.objects.filter(user=viewer).update(role="owner")


def test_lab_names_are_unique_ignoring_case(lab: Lab) -> None:
    with pytest.raises(IntegrityError, match="labs_lab_name_uniq"), transaction.atomic():
        make_lab(name="MYCOLOGY")


def test_lab_codes_are_unique(lab: Lab) -> None:
    with pytest.raises(IntegrityError, match="labs_lab_code_uniq"), transaction.atomic():
        make_lab(code="MYC")


@pytest.mark.parametrize("code", ["", "M", "myc", "MY-C", "MY C"])
def test_lab_codes_are_two_to_ten_upper_case_letters_or_digits(code: str) -> None:
    with pytest.raises(IntegrityError, match="labs_lab_code_format"), transaction.atomic():
        make_lab(code=code)


@pytest.mark.parametrize("code", ["MY", "B12", "ABCDEFGHIJ"])
def test_valid_lab_codes_are_accepted(code: str) -> None:
    assert make_lab(code=code).code == code


def test_a_blank_lab_name_is_refused() -> None:
    with pytest.raises(IntegrityError, match="labs_lab_name_not_blank"), transaction.atomic():
        make_lab(name="")


def test_a_lab_with_members_cannot_be_deleted(lab: Lab, viewer: User) -> None:
    with pytest.raises(ProtectedError):
        lab.delete()


def test_a_user_with_memberships_cannot_be_deleted(lab: Lab, viewer: User) -> None:
    with pytest.raises(ProtectedError):
        viewer.delete()
    assert membership(viewer, lab).role == Role.VIEWER

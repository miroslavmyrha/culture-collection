"""Selectors scope themselves: given any lab, they return nothing outside the access."""

import pytest

from cultures.core.exceptions import NotFound
from cultures.labs import selectors
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.users.models import User

pytestmark = pytest.mark.django_db


def test_the_lab_list_holds_only_the_users_labs(lab: Lab, other_lab: Lab, viewer: User) -> None:
    assert list(selectors.lab_list(access=access_for(viewer))) == [lab]


def test_a_lab_outside_the_access_is_not_found(lab: Lab, outsider: User) -> None:
    with pytest.raises(NotFound):
        selectors.lab_get(access=access_for(outsider), public_id=str(lab.public_id))


@pytest.mark.parametrize("public_id", ["not-a-uuid", "", "00000000-0000-4000-8000-000000000999"])
def test_malformed_and_missing_lab_ids_are_not_found(public_id: str, viewer: User) -> None:
    with pytest.raises(NotFound):
        selectors.lab_get(access=access_for(viewer), public_id=public_id)


def test_members_of_a_lab_outside_the_access_stay_hidden(
    lab: Lab, viewer: User, outsider: User
) -> None:
    # Defence in depth: the viewset resolves the lab through the access first, but a later
    # caller that passes any lab still gets only rows the access may see.
    assert list(selectors.member_list(access=access_for(outsider), lab=lab)) == []
    assert [m.user for m in selectors.member_list(access=access_for(viewer), lab=lab)] == [viewer]

"""My labs through the API: read only, scoped to my memberships, with my role."""

from uuid import uuid4

import pytest

from cultures.core.testing import assert_problem, logged_in
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.users.models import User

from .conftest import LAB_URL, LABS_URL, make_lab, make_user, member_of

pytestmark = pytest.mark.django_db


def test_the_list_shows_my_labs_with_my_role_by_name(
    lab: Lab, other_lab: Lab, curator: User
) -> None:
    other_lab.memberships.create(user=curator, role=Role.VIEWER)
    make_lab(name="Zoology")  # not a member
    response = logged_in(curator).get(LABS_URL)
    assert response.json() == {
        "count": 2,
        "next": None,
        "previous": None,
        "results": [
            {
                "public_id": str(other_lab.public_id),
                "name": "Bacteriology",
                "code": "BAC",
                "my_role": "viewer",
            },
            {
                "public_id": str(lab.public_id),
                "name": "Mycology",
                "code": "MYC",
                "my_role": "curator",
            },
        ],
    }


def test_a_user_in_no_lab_gets_an_empty_list(lab: Lab, stranger: User) -> None:
    assert logged_in(stranger).get(LABS_URL).json()["results"] == []


@pytest.mark.parametrize("role", list(Role))
def test_every_member_reads_the_lab_with_their_role(role: Role, lab: Lab) -> None:
    user = member_of(lab, role, f"as-{role}")
    assert logged_in(user).get(LAB_URL).json() == {
        "public_id": str(lab.public_id),
        "name": "Mycology",
        "code": "MYC",
        "my_role": str(role),
    }


def test_hidden_missing_and_malformed_labs_look_the_same(lab: Lab, outsider: User) -> None:
    client = logged_in(outsider)
    bodies = [
        assert_problem(client.get(url), 404, "not_found")
        for url in (LAB_URL, f"{LABS_URL}{uuid4()}/", f"{LABS_URL}not-a-uuid/")
    ]
    assert bodies[0] == bodies[1] == bodies[2]


@pytest.mark.parametrize(
    ("method", "url"),
    [("post", LABS_URL), ("put", LAB_URL), ("patch", LAB_URL), ("delete", LAB_URL)],
)
def test_labs_cannot_be_created_or_changed_through_the_api(
    method: str, url: str, lab: Lab, manager: User
) -> None:
    # Staff create and change labs in Django admin. Not even a manager writes them here.
    before = list(Lab.objects.values())
    response = getattr(logged_in(manager), method)(
        url, {"name": "Renamed", "code": "REN"}, content_type="application/json"
    )
    assert_problem(response, 405, "method_not_allowed")
    assert list(Lab.objects.values()) == before


def test_staff_and_superusers_get_no_shortcut(lab: Lab) -> None:
    admin = make_user("root", is_staff=True, is_superuser=True)
    client = logged_in(admin)
    assert client.get(LABS_URL).json()["results"] == []
    assert_problem(client.get(LAB_URL), 404, "not_found")

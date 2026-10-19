"""The role model in code and the access object built from memberships."""

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from rest_framework.request import Request

from cultures.labs.access import Access, access_for, access_of
from cultures.labs.models import Lab
from cultures.labs.permissions import GRANTS, ROLE_PERMS, ROLES, Perm, Role, may_grant, outranks
from cultures.users.models import User

from .conftest import make_user, member_of

V, T, C, M = Role.VIEWER, Role.TECHNICIAN, Role.CURATOR, Role.MANAGER

# The reviewed matrix of the permissions (#9, #11, #10 and #12, #14): (perm, roles that have it).
MATRIX = [
    (Perm.VIEW_LAB, {V, T, C, M}),
    (Perm.VIEW_MEMBERS, {V, T, C, M}),
    (Perm.MANAGE_MEMBERS, {M}),
    (Perm.VIEW_STRAINS, {V, T, C, M}),
    (Perm.HANDLE_VIALS, {T, C, M}),
    (Perm.VIEW_STORAGE, {V, T, C, M}),
    (Perm.MANAGE_STORAGE, {C, M}),
    (Perm.MANAGE_STRAINS, {C, M}),
    (Perm.VIEW_DEPOSITS, {C, M}),
    (Perm.MANAGE_DEPOSITS, {C, M}),
    (Perm.MANAGE_MTA, {M}),
    (Perm.MANAGE_DISTRIBUTION, {C, M}),
]


@pytest.mark.parametrize(("perm", "holders"), MATRIX, ids=[str(p) for p, _ in MATRIX])
def test_each_permission_belongs_to_exactly_these_roles(perm: Perm, holders: set[Role]) -> None:
    assert {role for role in Role if perm in ROLE_PERMS[role]} == holders


def test_the_matrix_names_every_permission() -> None:
    assert {perm for perm, _ in MATRIX} == set(Perm)


def test_roles_are_ordered_and_every_role_is_ranked() -> None:
    assert ROLES == (V, T, C, M)
    assert set(ROLES) == set(Role) == set(GRANTS)


@pytest.mark.parametrize(("lower", "higher"), [(V, T), (T, C), (C, M)])
def test_a_higher_role_has_everything_of_the_lower_one_and_more(lower: Role, higher: Role) -> None:
    assert ROLE_PERMS[lower] < ROLE_PERMS[higher]


def test_every_permission_is_granted_by_some_role() -> None:
    assert set().union(*GRANTS.values()) == set(Perm)


@pytest.mark.parametrize("role", list(Role))
def test_a_manager_may_grant_every_role(role: Role) -> None:
    assert may_grant(M, role)


@pytest.mark.parametrize("granter", [V, T, C])
@pytest.mark.parametrize("role", list(Role))
def test_nobody_below_manager_may_grant_anything(granter: Role, role: Role) -> None:
    assert not may_grant(granter, role)


def test_a_lower_role_that_manages_members_still_grants_only_up_to_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Not possible with today's map (only managers manage members, and nothing is above
    # them). The rule must hold the day a lower role gets member management.
    monkeypatch.setitem(ROLE_PERMS, C, ROLE_PERMS[C] | {Perm.MANAGE_MEMBERS})
    assert [role for role in ROLES if may_grant(C, role)] == [V, T, C]


def test_outranks_is_strict() -> None:
    assert outranks(M, C)
    assert not outranks(C, C)
    assert not outranks(V, T)


# The access object


@pytest.mark.django_db
def test_access_maps_each_lab_to_the_users_role(lab: Lab, other_lab: Lab, curator: User) -> None:
    other_lab.memberships.create(user=curator, role=M)
    access = access_for(curator)
    assert dict(access.roles) == {lab.pk: C, other_lab.pk: M}
    assert access.labs_with(Perm.VIEW_LAB) == {lab.pk, other_lab.pk}
    assert access.labs_with(Perm.MANAGE_MEMBERS) == {other_lab.pk}
    assert (access.can(Perm.MANAGE_STRAINS, lab.pk), access.can(Perm.MANAGE_MEMBERS, lab.pk)) == (
        True,
        False,
    )


@pytest.mark.django_db
def test_an_inactive_user_has_no_labs(lab: Lab) -> None:
    user = member_of(lab, M, "gone", is_active=False)
    access = access_for(user)
    assert dict(access.roles) == {}
    assert access.labs_with(Perm.VIEW_LAB) == frozenset()
    assert not access.can(Perm.VIEW_LAB, lab.pk)


@pytest.mark.django_db
def test_a_superuser_has_no_labs_without_memberships(lab: Lab) -> None:
    root = make_user("root", is_staff=True, is_superuser=True)
    assert access_for(root).labs_with(Perm.VIEW_LAB) == frozenset()


def test_a_user_without_memberships_can_do_nothing() -> None:
    access = Access(user=User(username="nobody"))
    assert (access.role_in(1), access.can(Perm.VIEW_LAB, 1), access.labs_with(Perm.VIEW_LAB)) == (
        None,
        False,
        frozenset(),
    )


@pytest.mark.django_db
def test_the_request_builds_its_access_once(lab: Lab, viewer: User) -> None:
    http = RequestFactory().get("/")

    def drf_request() -> Request:
        request = Request(http)  # one HTTP request, seen by two DRF wrappers
        request.user = viewer
        return request

    with CaptureQueriesContext(connection) as queries:
        first, second = access_of(drf_request()), access_of(drf_request())
    assert first is second
    assert len(queries) == 1
    assert dict(first.roles) == {lab.pk: V}

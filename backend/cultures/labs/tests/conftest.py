"""People and labs for the role matrix, named after what they are.

- lab: the lab under test, with one member of every role (viewer, technician,
  curator, manager). Its public_id is fixed, so URL constants can name it.
- other_lab: another lab, managed by `outsider`. The outsider has the highest
  role, only elsewhere: a 404 for them comes from the scope, never from the role.
"""

import itertools
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from django.contrib.auth.models import update_last_login
from django.contrib.auth.signals import user_logged_in
from model_bakery import baker

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import ActorKind, Channel
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.users.models import User

LAB_ID = UUID("00000000-0000-4000-8000-00000000000a")
LABS_URL = "/api/v1/labs/"
LAB_URL = f"{LABS_URL}{LAB_ID}/"
MEMBERS_URL = f"{LAB_URL}members/"

_seq = itertools.count(1)


def make_lab(**fields: Any) -> Lab:
    n = next(_seq)
    lab: Lab = baker.make(Lab, **{"name": f"Lab {n}", "code": f"L{n:03}", **fields})
    return lab


def make_user(username: str, **fields: Any) -> User:
    user: User = baker.make(User, username=username, **fields)
    return user


def member_of(lab: Lab, role: Role, username: str, **fields: Any) -> User:
    user = make_user(username, **fields)
    baker.make(Membership, user=user, lab=lab, role=role)
    return user


def membership(user: User, lab: Lab) -> Membership:
    return Membership.objects.get(user=user, lab=lab)


def snapshot() -> list[tuple[int, int, int, str]]:
    """Every membership as (pk, user, lab, role): a refused write must leave this as it was."""
    return list(Membership.objects.order_by("pk").values_list("pk", "user_id", "lab_id", "role"))


@pytest.fixture(autouse=True)
def _no_last_login_update() -> Iterator[None]:
    """Logging in writes users.last_login: keep the row trigger's history about our writes."""
    user_logged_in.disconnect(dispatch_uid="update_last_login")
    yield
    user_logged_in.connect(update_last_login, dispatch_uid="update_last_login")


@pytest.fixture
def lab() -> Lab:
    return make_lab(public_id=LAB_ID, name="Mycology", code="MYC")


@pytest.fixture
def other_lab() -> Lab:
    return make_lab(name="Bacteriology", code="BAC")


@pytest.fixture
def viewer(lab: Lab) -> User:
    return member_of(lab, Role.VIEWER, "viewer")


@pytest.fixture
def technician(lab: Lab) -> User:
    return member_of(lab, Role.TECHNICIAN, "technician")


@pytest.fixture
def curator(lab: Lab) -> User:
    return member_of(lab, Role.CURATOR, "curator")


@pytest.fixture
def manager(lab: Lab) -> User:
    return member_of(lab, Role.MANAGER, "manager")


@pytest.fixture
def outsider(other_lab: Lab) -> User:
    return member_of(other_lab, Role.MANAGER, "outsider")


@pytest.fixture
def stranger() -> User:
    """Active, in no lab: the user a manager adds."""
    return make_user("stranger", first_name="Sam", last_name="Stranger")


@pytest.fixture
def team(viewer: User, technician: User, curator: User, manager: User) -> dict[Role, User]:
    return {
        Role.VIEWER: viewer,
        Role.TECHNICIAN: technician,
        Role.CURATOR: curator,
        Role.MANAGER: manager,
    }


@pytest.fixture
def manager_access(manager: User) -> Access:
    return access_for(manager)


@pytest.fixture
def as_manager(manager: User) -> Iterator[AuditContext]:
    """Service tests run outside a request: the manager acting through the API channel."""
    with audit_context(channel=Channel.API, actor=manager, request_id="req-1") as context:
        yield context


@pytest.fixture
def as_system() -> Iterator[AuditContext]:
    """The trusted layer outside a request: a command."""
    with audit_context(
        channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label="command:test"
    ) as context:
        yield context

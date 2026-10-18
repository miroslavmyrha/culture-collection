"""Every service that changes memberships or deactivates users takes the lab lock first.

The walk covers every public function of cultures.labs.services and
cultures.users.services. Each one either has a scenario here, run with the
SQL captured, or a reviewed exemption with its reason. A new service fails
until someone puts it on one side. For each scenario the captured SQL must show:
- a lock on the lab row (SELECT ... FROM "labs_lab" ... FOR UPDATE).
- every read of the lab's managers (a membership query on role 'manager')
  after that lock, so it reads committed data.
- the first lock on a user row before the first lab lock (lock order: users,
  then labs, then memberships), and such a lock in every service that adds a
  member or deactivates users (LOCKS_USER): a membership cannot appear for a
  user while the user is being deactivated.
SQL is text, so this proves the order of statements, not what PostgreSQL
does with them: the thread races in test_concurrency.py prove that part.
"""

import inspect
from collections.abc import Callable
from types import ModuleType

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cultures.audit.context import AuditContext
from cultures.labs import services as labs
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.users import services as users
from cultures.users.models import User

from .conftest import make_user, member_of, membership

pytestmark = pytest.mark.django_db
REASON = "invariant scenario"

Scenario = Callable[[Lab], Callable[[], object]]


def _two_managers(lab: Lab) -> tuple[User, User]:
    return member_of(lab, Role.MANAGER, "first"), member_of(lab, Role.MANAGER, "second")


def membership_create(lab: Lab) -> Callable[[], object]:
    user = make_user("new")
    return lambda: labs.membership_create(lab=lab, user=user, role=Role.VIEWER)


def membership_set_role(lab: Lab) -> Callable[[], object]:
    first, _ = _two_managers(lab)
    return lambda: labs.membership_set_role(membership=membership(first, lab), role=Role.VIEWER)


def membership_delete(lab: Lab) -> Callable[[], object]:
    first, _ = _two_managers(lab)
    return lambda: labs.membership_delete(membership=membership(first, lab))


def member_add(lab: Lab) -> Callable[[], object]:
    first, _ = _two_managers(lab)
    user = make_user("new")
    return lambda: labs.member_add(access=access_for(first), lab=lab, user=user, role=Role.VIEWER)


def member_change_role(lab: Lab) -> Callable[[], object]:
    first, second = _two_managers(lab)
    return lambda: labs.member_change_role(
        access=access_for(first), membership=membership(second, lab), role=Role.VIEWER
    )


def member_remove(lab: Lab) -> Callable[[], object]:
    first, second = _two_managers(lab)
    return lambda: labs.member_remove(access=access_for(first), membership=membership(second, lab))


def user_deactivate(lab: Lab) -> Callable[[], object]:
    first, _ = _two_managers(lab)
    return lambda: users.user_deactivate(user=first, reason=REASON)


def users_deactivate(lab: Lab) -> Callable[[], object]:
    first, _ = _two_managers(lab)
    viewer = member_of(lab, Role.VIEWER, "viewer")
    return lambda: users.users_deactivate(users=[first, viewer], reason=REASON)


def user_erase(lab: Lab) -> Callable[[], object]:
    first, _ = _two_managers(lab)
    return lambda: users.user_erase(user=first, reason=REASON)


def users_deactivation_check(lab: Lab) -> Callable[[], object]:
    first, _ = _two_managers(lab)
    return lambda: labs.users_deactivation_check(users=[first])


SCENARIOS: dict[str, Scenario] = {
    scenario.__name__: scenario
    for scenario in (
        membership_create,
        membership_set_role,
        membership_delete,
        member_add,
        member_change_role,
        member_remove,
        user_deactivate,
        users_deactivate,
        user_erase,
        users_deactivation_check,
    )
}

# Services that lock a user row: the new member's, or the users being deactivated or erased.
LOCKS_USER = {
    "membership_create",
    "member_add",
    "user_deactivate",
    "users_deactivate",
    "user_erase",
}

# Public services that neither change memberships nor make a user inactive.
EXEMPT: dict[str, str] = {
    "lab_create": "a new lab has no members yet",
    "lab_update": "changes the name and code only (and locks the lab anyway)",
    "labs_left_without_manager": "a read for forms, the services decide under the locks",
    "user_create": "a new user is in no lab",
    "user_update": "profile fields only",
    "user_activate": "activating can add an active manager, never remove one",
    "user_set_staff": "admin access, not a lab role",
    "user_set_superuser": "Django permissions, not a lab role",
    "user_set_password": "the password only",
    "user_login_limits_clear": "deletes login counters, no lab role and no user row",
    "superuser_create": "a new user is in no lab",
}


def public_services(module: ModuleType) -> set[str]:
    return {
        name
        for name, function in inspect.getmembers(module, inspect.isfunction)
        if function.__module__ == module.__name__ and not name.startswith("_")
    }


def test_every_public_service_has_a_scenario_or_a_reviewed_exemption() -> None:
    found = public_services(labs) | public_services(users)
    assert len(found) > 10  # the walk found the services, it did not pass on an empty set
    assert sorted(found - set(SCENARIOS) - set(EXEMPT)) == []
    assert sorted((set(SCENARIOS) | set(EXEMPT)) - found) == []  # no stale entries


def first(statements: list[str], match: Callable[[str], bool]) -> int | None:
    return next((i for i, sql in enumerate(statements) if match(sql)), None)


def locks(table: str) -> Callable[[str], bool]:
    return lambda sql: sql.startswith("SELECT") and f'FROM "{table}"' in sql and " FOR " in sql


def reads_managers(sql: str) -> bool:
    return 'FROM "labs_membership"' in sql and '"labs_membership"."role" = \'manager\'' in sql


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_lab_lock_comes_before_the_managers_are_read(
    name: str, lab: Lab, as_system: AuditContext
) -> None:
    call = SCENARIOS[name](lab)
    with CaptureQueriesContext(connection) as captured:
        call()
    statements = [query["sql"] for query in captured.captured_queries]
    lab_lock = first(statements, locks("labs_lab"))
    assert lab_lock is not None, f"{name} never locks the lab:\n" + "\n".join(statements)
    early = [sql for sql in statements[:lab_lock] if reads_managers(sql)]
    assert early == [], f"{name} reads the managers before the lab lock"
    user_lock = first(statements, locks("users_user"))
    assert (user_lock is not None) == (name in LOCKS_USER), f"{name}: user lock {user_lock}"
    assert user_lock is None or user_lock < lab_lock, f"{name} locks a user after a lab"

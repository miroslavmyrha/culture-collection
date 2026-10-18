"""A lab keeps an active manager on every path that changes members or users (#35).

An inactive user keeps the membership but manages nobody, so only active
managers count: in the trusted and the checked services, the API, the admin
lab form, and when a user is deactivated (one, many, or in the admin user
form). A refused attempt changes nothing and records nothing: no event, no
row change.
"""

from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent, RowChange
from cultures.core.exceptions import Forbidden
from cultures.core.testing import assert_problem, logged_in
from cultures.labs import services
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.services import LastManager
from cultures.users.models import User
from cultures.users.services import user_deactivate, users_deactivate

from .conftest import MEMBERS_URL, make_lab, make_user, member_of, membership, snapshot
from .test_admin import change_lab, existing

pytestmark = pytest.mark.django_db
REASON = "left the institute"


def users() -> list[tuple[int, bool]]:
    return list(User.objects.order_by("pk").values_list("pk", "is_active"))


def state() -> tuple[Any, ...]:
    """Everything a refused attempt must leave as it was, the audit trail included."""
    return snapshot(), users(), AuditEvent.objects.count(), RowChange.objects.count()


@pytest.fixture
def gone(lab: Lab) -> User:
    """A manager of the lab who was deactivated: the membership stays, the rights do not."""
    return member_of(lab, Role.MANAGER, "gone", is_active=False)


# Stepping down while the only other manager is inactive


def demote(user: User, lab: Lab) -> None:
    services.member_change_role(
        access=access_for(user), membership=membership(user, lab), role=Role.VIEWER
    )


def remove(user: User, lab: Lab) -> None:
    services.member_remove(access=access_for(user), membership=membership(user, lab))


def set_role(user: User, lab: Lab) -> None:
    services.membership_set_role(membership=membership(user, lab), role=Role.VIEWER)


def delete(user: User, lab: Lab) -> None:
    services.membership_delete(membership=membership(user, lab))


@pytest.mark.parametrize("step_down", [demote, remove, set_role, delete])
@pytest.mark.usefixtures("gone")
def test_an_inactive_manager_does_not_count(
    step_down: Callable[[User, Lab], None], lab: Lab, manager: User, as_manager: AuditContext
) -> None:
    before = state()
    with pytest.raises(LastManager) as error:
        step_down(manager, lab)
    assert (error.value.status_code, error.value.code) == (422, "last_manager")
    assert state() == before


@pytest.mark.parametrize("step_down", [demote, remove, set_role, delete])
def test_an_active_second_manager_lets_one_step_down(
    step_down: Callable[[User, Lab], None], lab: Lab, manager: User, as_manager: AuditContext
) -> None:
    member_of(lab, Role.MANAGER, "stays")
    step_down(manager, lab)
    assert not Membership.objects.filter(user=manager, role=Role.MANAGER).exists()


@pytest.mark.usefixtures("gone")
def test_the_api_answers_last_manager_when_the_other_manager_is_inactive(
    lab: Lab, manager: User
) -> None:
    before = state()
    url = f"{MEMBERS_URL}{membership(manager, lab).public_id}/"
    response = logged_in(manager).patch(url, {"role": "viewer"}, content_type="application/json")
    assert_problem(response, 422, "last_manager")
    assert state() == before


# The grantor is re-read under the lock: deactivated after the access object was built


@pytest.mark.parametrize("action", ["add", "change", "remove"])
@pytest.mark.usefixtures("as_manager")
def test_a_grantor_deactivated_after_the_request_began_is_refused(
    action: str, lab: Lab, manager: User, viewer: User, stranger: User
) -> None:
    access = access_for(manager)  # built when the request started: still says manager
    member_of(lab, Role.MANAGER, "successor")
    user_deactivate(user=manager, reason=REASON)
    before = state()
    calls: dict[str, Callable[[], object]] = {
        "add": lambda: services.member_add(access=access, lab=lab, user=stranger, role=Role.VIEWER),
        "change": lambda: services.member_change_role(
            access=access, membership=membership(viewer, lab), role=Role.CURATOR
        ),
        "remove": lambda: services.member_remove(access=access, membership=membership(viewer, lab)),
    }
    with pytest.raises(Forbidden) as error:
        calls[action]()
    assert error.value.code == "permission_denied"
    assert state() == before


# Deactivating users


def test_the_last_active_manager_cannot_be_deactivated(
    lab: Lab, manager: User, viewer: User, as_system: AuditContext
) -> None:
    before = state()
    with pytest.raises(LastManager) as error:
        user_deactivate(user=manager, reason=REASON)
    assert (error.value.status_code, error.value.code) == (422, "last_manager")
    assert error.value.detail == (
        "This would leave Mycology (MYC) without an active manager."
        " Make another member a manager first."
    )
    assert state() == before
    assert User.objects.get(pk=manager.pk).is_active


@pytest.mark.usefixtures("gone")
def test_an_inactive_manager_is_no_replacement_for_deactivation(
    lab: Lab, manager: User, as_system: AuditContext
) -> None:
    before = state()
    with pytest.raises(LastManager):
        user_deactivate(user=manager, reason=REASON)
    assert state() == before


def test_a_manager_with_an_active_colleague_can_be_deactivated(
    lab: Lab, manager: User, as_system: AuditContext
) -> None:
    member_of(lab, Role.MANAGER, "colleague")
    user_deactivate(user=manager, reason=REASON)
    assert not User.objects.get(pk=manager.pk).is_active
    assert membership(manager, lab).role == Role.MANAGER  # kept, but it counts no more


def test_a_member_who_manages_nothing_can_be_deactivated(
    lab: Lab, manager: User, viewer: User, as_system: AuditContext
) -> None:
    user_deactivate(user=viewer, reason=REASON)
    assert not User.objects.get(pk=viewer.pk).is_active


def test_a_lab_already_without_an_active_manager_does_not_block_its_members(
    lab: Lab, gone: User, viewer: User, as_system: AuditContext
) -> None:
    user_deactivate(user=viewer, reason=REASON)
    assert not User.objects.get(pk=viewer.pk).is_active


def test_the_last_manager_of_any_one_lab_is_refused(
    lab: Lab, other_lab: Lab, manager: User, as_system: AuditContext
) -> None:
    member_of(lab, Role.MANAGER, "colleague")  # covered here ...
    Membership.objects.create(user=manager, lab=other_lab, role=Role.MANAGER)  # ... alone here
    before = state()
    with pytest.raises(LastManager) as error:
        user_deactivate(user=manager, reason=REASON)
    assert "Bacteriology (BAC)" in error.value.detail
    assert state() == before


def test_a_batch_that_holds_a_last_manager_deactivates_nobody(
    lab: Lab, viewer: User, manager: User, as_system: AuditContext
) -> None:
    """The viewer comes first by pk: every user of the batch is checked, not only the first."""
    assert viewer.pk < manager.pk
    before = state()
    with pytest.raises(LastManager):
        users_deactivate(users=[viewer, manager], reason=REASON)
    assert state() == before


def test_two_managers_deactivated_together_are_both_counted_as_leaving(
    lab: Lab, manager: User, as_system: AuditContext
) -> None:
    second = member_of(lab, Role.MANAGER, "second")
    before = state()
    with pytest.raises(LastManager):
        users_deactivate(users=[manager, second], reason=REASON)
    assert state() == before


def test_a_batch_that_leaves_every_lab_a_manager_goes_through(
    lab: Lab, manager: User, viewer: User, curator: User, as_system: AuditContext
) -> None:
    assert users_deactivate(users=[viewer, curator], reason=REASON) == 2
    assert [u.is_active for u in User.objects.filter(pk__in=[viewer.pk, curator.pk])] == [
        False,
        False,
    ]


def test_deactivation_locks_every_lab_of_the_users_in_pk_order(
    monkeypatch: pytest.MonkeyPatch, as_system: AuditContext
) -> None:
    """Memberships made in the reverse order of the labs: the locks still follow the lab pk."""
    labs = [make_lab() for _ in range(3)]
    leaving, colleague = make_user("leaving"), make_user("colleague")
    for lab in reversed(labs):
        Membership.objects.create(user=leaving, lab=lab, role=Role.MANAGER)
        Membership.objects.create(user=colleague, lab=lab, role=Role.MANAGER)
    locked: list[int] = []
    original = services._lock_lab

    def recording(lab_id: int) -> Lab:
        locked.append(lab_id)
        return original(lab_id)

    monkeypatch.setattr(services, "_lock_lab", recording)
    user_deactivate(user=leaving, reason=REASON)
    assert locked == sorted(lab.pk for lab in labs)


def test_a_refused_deactivation_records_nothing_for_its_request(
    lab: Lab, manager: User, as_system: AuditContext
) -> None:
    """The refusal rolls the whole service back: no event and no row change carry its id."""
    with pytest.raises(LastManager):
        user_deactivate(user=manager, reason=REASON)
    request_id = as_system.request_id
    assert not AuditEvent.objects.filter(request_id=request_id).exists()
    assert not RowChange.objects.filter(request_id=request_id).exists()


# Admin: the lab form and the user form


@pytest.fixture
def admin_client() -> Client:
    return logged_in(make_user("staff", is_staff=True, is_superuser=True))


def test_the_lab_form_does_not_count_an_inactive_manager(
    admin_client: Client, lab: Lab, manager: User, gone: User
) -> None:
    before = state()
    rows = [existing(membership(manager, lab), role="viewer"), existing(membership(gone, lab))]
    response = change_lab(admin_client, lab, rows)
    assert response.status_code == 200
    assert "A lab needs at least one active manager." in response.content.decode()
    assert state() == before


def test_a_lab_with_an_inactive_member_can_still_be_saved(
    admin_client: Client, lab: Lab, manager: User, gone: User, viewer: User
) -> None:
    rows = [
        existing(membership(manager, lab)),
        existing(membership(gone, lab), role="viewer"),
        existing(membership(viewer, lab), role="curator"),
    ]
    response = change_lab(admin_client, lab, rows)
    assert response.status_code == 302, response.content
    assert (membership(gone, lab).role, membership(viewer, lab).role) == (
        Role.VIEWER,
        Role.CURATOR,
    )


def test_a_lab_whose_only_manager_is_inactive_stays_editable(
    admin_client: Client, lab: Lab, gone: User, viewer: User
) -> None:
    """Staff can change other members of such a lab, not only name a new manager."""
    rows = [existing(membership(gone, lab)), existing(membership(viewer, lab), role="technician")]
    response = change_lab(admin_client, lab, rows)
    assert response.status_code == 302, response.content
    assert membership(viewer, lab).role == Role.TECHNICIAN


def user_form(user: User, **changes: Any) -> dict[str, Any]:
    """The admin user change form as the browser posts it: unchecked boxes are absent."""
    data: dict[str, Any] = {
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        **{flag: "on" for flag in ("is_active", "is_staff", "is_superuser") if getattr(user, flag)},
        **changes,
    }
    return {key: value for key, value in data.items() if value is not None}


def deactivate_in_admin(client: Client, user: User) -> Any:
    url = reverse("admin:users_user_change", args=[user.pk])
    return client.post(url, user_form(user, is_active=None, reason=REASON))


def test_the_user_form_refuses_to_deactivate_the_last_active_manager(
    admin_client: Client, lab: Lab, manager: User
) -> None:
    before = state()
    response = deactivate_in_admin(admin_client, manager)
    assert response.status_code == 200
    assert (
        "This user is the last active manager of Mycology (MYC)."
        " Make another member a manager first." in response.content.decode()
    )
    assert state() == before


def test_the_user_form_deactivates_a_manager_with_a_replacement(
    admin_client: Client, lab: Lab, manager: User
) -> None:
    member_of(lab, Role.MANAGER, "successor")
    response = deactivate_in_admin(admin_client, manager)
    assert response.status_code == 302, response.content
    assert not User.objects.get(pk=manager.pk).is_active
    assert AuditEvent.objects.get().event_type == "user_deactivated"

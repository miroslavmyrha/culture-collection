"""user_erase turns a person's user row into a tombstone (#37), and the admin's "Erase user".

Every refusal asserts that nothing changed: the user row, the memberships,
the sessions and the audit trail.
"""

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.core.exceptions import RuleViolation
from cultures.core.testing import logged_in
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.services import LastManager
from cultures.users import login_limits, services
from cultures.users.admin import ERASE_CONFIRM, NO_NAMES
from cultures.users.models import LoginFailures, User

from .conftest import PASSWORD, make_user, trail
from .test_admin import form_of
from .test_login_limits import HOME, admin, api

pytestmark = pytest.mark.django_db
REASON = "erasure request 2026-114, checked by the data protection office"


def erase_url(user: User) -> str:
    return reverse("admin:users_user_erase", args=[user.pk])


def change_url(user: User) -> str:
    return reverse("admin:users_user_change", args=[user.pk])


def lab_with(*members: tuple[User, Role]) -> Lab:
    lab: Lab = baker.make(
        Lab, name=f"Lab {members[0][0].username}", code="L" + str(Lab.objects.count() + 10)
    )
    for user, role in members:
        baker.make(Membership, lab=lab, user=user, role=role)
    return lab


def state(user: User) -> tuple[Any, ...]:
    """Everything a refused erasure must leave as it was."""
    row = User.objects.filter(pk=user.pk).values().get()
    memberships = list(Membership.objects.order_by("pk").values_list("pk", "user_id", "role"))
    return row, memberships, Session.objects.count(), LoginFailures.objects.count(), trail()


@pytest.fixture
def person() -> User:
    """The user to erase, with a password, staff status and a session."""
    user = make_user("ada.l", first_name="Ada", last_name="Lovelace", is_staff=True)
    user.set_password(PASSWORD)
    user.save()
    logged_in(user)  # a session row in django_session
    return user


def test_erasure_leaves_a_tombstone_that_keeps_the_ids(person: User, audited: AuditContext) -> None:
    joined, public_id, pk = person.date_joined, person.public_id, person.pk

    erased = services.user_erase(user=person, reason=REASON)

    erased.refresh_from_db()
    assert (erased.pk, erased.public_id, erased.date_joined) == (pk, public_id, joined)
    assert erased.username == f"erased-{public_id}"
    assert (erased.first_name, erased.last_name, erased.email) == ("", "", "")
    assert not erased.has_usable_password()
    assert (erased.is_active, erased.is_staff, erased.is_superuser) == (False, False, False)
    assert erased.erased_at is not None
    assert erased.is_erased


def test_erasure_records_its_event_with_the_reason_and_no_values(
    person: User, staff: User, audited: AuditContext
) -> None:
    services.user_erase(user=person, reason=REASON)

    (event,) = AuditEvent.objects.filter(event_type="user_erased")
    assert (event.actor, event.reason, event.subject_id) == (staff, REASON, person.public_id)
    assert event.changes == {
        "username": "changed",
        "first_name": "changed",
        "last_name": "changed",
        "email": "changed",
        "is_active": [True, False],
        "is_staff": [True, False],
        "is_superuser": [False, False],
        "has_usable_password": [True, False],
        "memberships": [0, 0],
        "sessions": [1, 0],
        "login_failure_counters": [0, 0],
    }


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_without_a_reason_nothing_is_erased(
    person: User, audited: AuditContext, reason: str | None
) -> None:
    before = state(person)
    with pytest.raises(RuleViolation) as refused:
        services.user_erase(user=person, reason=reason)
    assert refused.value.code == "reason_required"
    assert state(person) == before


def test_the_sessions_of_the_user_end_and_the_others_stay(
    person: User, member: User, audited: AuditContext
) -> None:
    other = logged_in(member)
    assert Session.objects.count() == 2

    services.user_erase(user=person, reason=REASON)

    assert Session.objects.count() == 1
    assert other.get("/api/v1/auth/me/").status_code == 200


def test_the_login_counters_of_the_account_go(person: User, audited: AuditContext) -> None:
    api(Client(), "ada.l", "wrong", HOME)
    assert LoginFailures.objects.filter(account=login_limits.account_key("ada.l")).exists()

    erased = services.user_erase(user=person, reason=REASON)

    assert not LoginFailures.objects.filter(account=login_limits.account_key("ada.l")).exists()
    (event,) = AuditEvent.objects.filter(event_type="user_erased")
    assert event.changes["login_failure_counters"] == [2, 0]  # its own counter and its pair
    assert erased.is_erased


def test_the_memberships_end_through_the_labs_service(
    person: User, member: User, audited: AuditContext
) -> None:
    lab = lab_with((person, Role.MANAGER), (member, Role.MANAGER))
    other = lab_with((member, Role.MANAGER), (person, Role.VIEWER))

    services.user_erase(user=person, reason=REASON)

    assert not Membership.objects.filter(user=person).exists()
    assert Membership.objects.filter(user=member).count() == 2
    removed = AuditEvent.objects.filter(event_type="member_removed").order_by("pk")
    assert [(e.lab_id, e.changes["user"]) for e in removed] == [
        (lab.pk, [str(person.public_id), None]),
        (other.pk, [str(person.public_id), None]),
    ]
    (event,) = AuditEvent.objects.filter(event_type="user_erased")
    assert event.changes["memberships"] == [2, 0]


def test_the_last_active_manager_of_a_lab_is_not_erased(
    person: User, member: User, audited: AuditContext
) -> None:
    lab_with((member, Role.MANAGER))
    lab_with((person, Role.MANAGER), (member, Role.CURATOR))
    before = state(person)

    with pytest.raises(LastManager) as refused:
        services.user_erase(user=person, reason=REASON)

    assert refused.value.code == "last_manager"
    assert "without an active manager" in refused.value.detail
    assert state(person) == before


def test_an_inactive_manager_of_a_lab_without_an_active_one_is_not_erased(
    person: User, member: User, audited: AuditContext
) -> None:
    """membership_delete keeps the rule for everybody: a lab never loses a manager row it needs."""
    lab_with((person, Role.MANAGER), (member, Role.VIEWER))
    User.objects.filter(pk=person.pk).update(is_active=False)
    before = state(person)

    with pytest.raises(LastManager):
        services.user_erase(user=person, reason=REASON)

    assert state(person) == before


def test_the_last_active_superuser_is_not_erased(staff: User, member: User) -> None:
    """staff is the only active superuser; an inactive one does not count."""
    make_user("retired", is_superuser=True, is_active=False)
    with audit_context(channel=Channel.COMMAND, actor=member):
        before = state(staff)
        with pytest.raises(services.LastSuperuser) as refused:
            services.user_erase(user=staff, reason=REASON)
    assert refused.value.code == "last_superuser"
    assert state(staff) == before


def test_a_superuser_is_erased_when_another_active_one_remains(
    staff: User, audited: AuditContext
) -> None:
    second = make_user("second-root", is_staff=True, is_superuser=True)
    erased = services.user_erase(user=second, reason=REASON)
    assert (erased.is_superuser, erased.is_erased) == (False, True)


def test_a_second_erasure_changes_nothing_and_records_nothing(
    person: User, audited: AuditContext
) -> None:
    first = services.user_erase(user=person, reason=REASON)
    before = state(person)

    second = services.user_erase(user=person, reason=REASON)

    assert (second.pk, second.erased_at) == (first.pk, first.erased_at)
    assert state(person) == before


def test_an_erased_user_cannot_be_reactivated_or_changed(
    person: User, audited: AuditContext
) -> None:
    services.user_erase(user=person, reason=REASON)
    before = state(person)
    attempts: list[Callable[[], object]] = [
        lambda: services.user_activate(user=person, reason=REASON),
        lambda: services.user_update(user=person, changes={"first_name": "Ada"}),
        lambda: services.user_set_password(user=person, raw_password=PASSWORD),
        lambda: services.user_set_staff(user=person, is_staff=True, reason=REASON),
        lambda: services.user_set_superuser(user=person, is_superuser=True, reason=REASON),
        lambda: services.user_deactivate(user=person, reason=REASON),
    ]
    for attempt in attempts:
        with pytest.raises(services.UserErased) as refused:
            attempt()
        assert refused.value.code == "user_erased"
    assert state(person) == before


def test_the_database_refuses_to_revive_a_tombstone(person: User, audited: AuditContext) -> None:
    services.user_erase(user=person, reason=REASON)
    for change in ({"is_active": True}, {"email": "ada@example.org"}, {"username": "ada.l"}):
        with (
            pytest.raises(IntegrityError, match="users_user_erased_is_a_tombstone"),
            transaction.atomic(),
        ):
            User.objects.filter(pk=person.pk).update(**change)


def test_an_erased_user_cannot_sign_in(person: User, audited: AuditContext) -> None:
    erased = services.user_erase(user=person, reason=REASON)
    for username in ("ada.l", erased.username):
        assert api(Client(), username, PASSWORD, HOME) == "wrong"
        assert admin(Client(), username, PASSWORD, HOME) == "wrong"


def test_the_admin_log_shows_the_tombstone_name(
    admin_client: Client, staff: User, person: User, audited: AuditContext
) -> None:
    response = admin_client.post(change_url(person), form_of(person, first_name="Augusta"))
    assert response.status_code == 302
    assert LogEntry.objects.get(object_id=str(person.pk)).object_repr == "ada.l"

    erased = services.user_erase(user=person, reason=REASON)

    assert set(LogEntry.objects.values_list("object_repr", flat=True)) == {erased.username}


@pytest.mark.parametrize("username", ["erased-x", "erased-00000000-0000-4000-8000-000000000001"])
def test_a_live_user_cannot_take_a_tombstone_name(
    member: User, audited: AuditContext, username: str
) -> None:
    """Such a name could block the erasure of the user whose public id it holds."""
    before = state(member)
    with pytest.raises(services.ReservedUsername):
        services.user_create(username=username, password=None)
    with pytest.raises(services.ReservedUsername):
        services.user_update(user=member, changes={"username": username})
    assert state(member) == before


# The admin's "Erase user" page.


def test_the_change_form_links_to_the_erase_page(admin_client: Client, person: User) -> None:
    page = admin_client.get(change_url(person)).content.decode()
    assert erase_url(person) in page
    erase_page = admin_client.get(erase_url(person)).content.decode()
    assert NO_NAMES in erase_page
    assert ERASE_CONFIRM in erase_page


def test_staff_erase_a_user_with_a_reason(admin_client: Client, staff: User, person: User) -> None:
    response = admin_client.post(
        erase_url(person),
        {"confirm": "ada.l", "reason": REASON},
        headers={"X-Request-ID": "adm-erase"},
    )
    assert response.status_code == 302, response.content
    assert response["Location"] == change_url(person)
    (event,) = AuditEvent.objects.filter(event_type="user_erased")
    assert (event.actor, event.channel, event.request_id, event.reason) == (
        staff,
        Channel.WEB,
        "adm-erase",
        REASON,
    )
    log = LogEntry.objects.get(object_id=str(person.pk), action_flag=CHANGE)
    assert (log.user_id, log.object_repr) == (staff.pk, f"erased-{person.public_id}")
    page = admin_client.get(change_url(person)).content.decode()
    assert f"erased-{person.public_id}" in page
    assert "erased on" in page
    assert "Lovelace" not in page


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ({"confirm": "ada.l", "reason": "  "}, "This field is required."),
        ({"confirm": "ada.l"}, "This field is required."),
        ({"confirm": "ADA.L", "reason": REASON}, ERASE_CONFIRM),
        ({"reason": REASON}, "This field is required."),
    ],
)
def test_the_erase_page_refuses_a_missing_reason_or_confirmation(
    admin_client: Client, person: User, data: dict[str, str], error: str
) -> None:
    before = state(person)
    response = admin_client.post(erase_url(person), data)
    assert response.status_code == 200
    assert error in response.content.decode()
    assert state(person) == before


def test_the_erase_page_shows_the_last_manager_refusal(
    admin_client: Client, person: User, member: User
) -> None:
    lab = lab_with((person, Role.MANAGER), (member, Role.VIEWER))
    before = state(person)
    response = admin_client.post(erase_url(person), {"confirm": "ada.l", "reason": REASON})
    assert response.status_code == 200
    assert f"This would leave {lab.name} ({lab.code}) without an active manager" in (
        response.content.decode()
    )
    assert state(person) == before


def test_an_erased_user_is_read_only_in_the_admin(
    admin_client: Client, person: User, audited: AuditContext
) -> None:
    services.user_erase(user=person, reason=REASON)
    person.refresh_from_db()
    before = state(person)
    password_url = reverse("admin:auth_user_password_change", args=[person.pk])
    assert admin_client.get(erase_url(person)).status_code == 403
    assert admin_client.post(erase_url(person), {"confirm": person.username}).status_code == 403
    assert admin_client.get(password_url).status_code == 403
    response = admin_client.post(change_url(person), form_of(person, is_active=True, reason=REASON))
    assert response.status_code == 403
    assert state(person) == before


def test_the_admin_refuses_a_tombstone_name_on_a_live_user(
    admin_client: Client, member: User
) -> None:
    before = state(member)
    response = admin_client.post(change_url(member), form_of(member, username="erased-x"))
    assert response.status_code == 200
    assert services.ReservedUsername.default_detail in response.content.decode().replace(
        "&#x27;", "'"
    )
    added = admin_client.post(
        reverse("admin:users_user_add"), {"username": "erased-y", "usable_password": "false"}
    )
    assert added.status_code == 200
    assert not User.objects.filter(username="erased-y").exists()
    assert state(member) == before


def test_staff_without_the_change_permission_cannot_erase(person: User) -> None:
    viewer = make_user("viewer-staff", is_staff=True)
    viewer.user_permissions.add(Permission.objects.get(codename="view_user"))
    before = state(person)
    client = logged_in(viewer)
    assert client.get(erase_url(person)).status_code == 403
    assert client.post(erase_url(person), {"confirm": "ada.l", "reason": REASON}).status_code == 403
    assert state(person)[:2] == before[:2]


def test_a_lab_manager_cannot_add_an_erased_user(
    person: User, member: User, audited: AuditContext
) -> None:
    """The API answers as for a name that does not exist: nothing tells the tombstone apart."""
    lab = lab_with((member, Role.MANAGER))
    erased = services.user_erase(user=person, reason=REASON)
    before = state(member)
    answers = []
    for username in (erased.username, "ada.l", "nobody-at-all"):
        response = logged_in(member).post(
            f"/api/v1/labs/{lab.public_id}/members/",
            {"username": username, "role": "viewer"},
            content_type="application/json",
        )
        answers.append((response.status_code, response.json()["errors"][0]["code"]))
    assert answers == [(400, "does_not_exist")] * 3
    assert (state(member)[1], state(member)[4]) == (before[1], before[4])  # memberships, trail

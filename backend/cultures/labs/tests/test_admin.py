"""Staff create labs and their members in Django admin, through the audited services."""

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from cultures.audit.models import AuditEvent, Channel
from cultures.core.testing import logged_in
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.users.models import User

from .conftest import make_user, member_of, membership, snapshot

pytestmark = pytest.mark.django_db
PREFIX = "memberships"


@pytest.fixture
def staff() -> User:
    return make_user("staff", is_staff=True, is_superuser=True)


@pytest.fixture
def admin_client(staff: User) -> Client:
    return logged_in(staff)


def inline(rows: list[dict[str, Any]], initial: int = 0) -> dict[str, Any]:
    """The POST data of the membership inline: management form plus one block per row."""
    data: dict[str, Any] = {
        f"{PREFIX}-TOTAL_FORMS": len(rows),
        f"{PREFIX}-INITIAL_FORMS": initial,
        f"{PREFIX}-MIN_NUM_FORMS": 0,
        f"{PREFIX}-MAX_NUM_FORMS": 1000,
    }
    for i, row in enumerate(rows):
        data.update({f"{PREFIX}-{i}-{key}": value for key, value in row.items()})
    return data


def existing(m: Membership, **changes: Any) -> dict[str, Any]:
    return {"id": m.pk, "lab": m.lab_id, "user": m.user_id, "role": m.role, **changes}


def change_lab(client: Client, lab: Lab, rows: list[dict[str, Any]]) -> Any:
    url = reverse("admin:labs_lab_change", args=[lab.pk])
    body = {"name": lab.name, "code": lab.code, **inline(rows, initial=len(rows))}
    return client.post(url, body)


def test_staff_create_a_lab_with_its_first_manager(admin_client: Client, staff: User) -> None:
    head = make_user("head")
    body = {"name": "Virology", "code": "VIR", **inline([{"user": head.pk, "role": "manager"}])}
    response = admin_client.post(reverse("admin:labs_lab_add"), body)
    assert response.status_code == 302, response.content
    lab = Lab.objects.get(code="VIR")
    assert membership(head, lab).role == Role.MANAGER
    events = list(AuditEvent.objects.order_by("pk"))
    assert [(e.event_type, e.channel, e.actor, e.lab) for e in events] == [
        ("lab_created", Channel.WEB, staff, lab),
        ("member_added", Channel.WEB, staff, lab),
    ]


def test_staff_change_roles_and_remove_members(
    admin_client: Client, lab: Lab, manager: User, viewer: User
) -> None:
    response = change_lab(
        admin_client,
        lab,
        [existing(membership(manager, lab)), existing(membership(viewer, lab), role="curator")],
    )
    assert response.status_code == 302, response.content
    assert membership(viewer, lab).role == Role.CURATOR
    response = change_lab(
        admin_client,
        lab,
        [existing(membership(manager, lab)), existing(membership(viewer, lab), DELETE="on")],
    )
    assert response.status_code == 302, response.content
    assert not Membership.objects.filter(user=viewer).exists()
    assert [e.event_type for e in AuditEvent.objects.order_by("pk")] == [
        "member_role_changed",
        "member_removed",
    ]


def test_staff_hand_the_lab_to_a_new_manager_in_one_save(
    admin_client: Client, lab: Lab, manager: User, viewer: User
) -> None:
    rows = [
        existing(membership(manager, lab), role="viewer"),
        existing(membership(viewer, lab), role="manager"),
    ]
    response = change_lab(admin_client, lab, rows)
    assert response.status_code == 302, response.content
    assert (membership(manager, lab).role, membership(viewer, lab).role) == (
        Role.VIEWER,
        Role.MANAGER,
    )


@pytest.mark.parametrize("change", [{"role": "curator"}, {"DELETE": "on"}])
def test_the_last_manager_stays_with_a_form_error(
    change: dict[str, str], admin_client: Client, lab: Lab, manager: User
) -> None:
    before = snapshot()
    response = change_lab(admin_client, lab, [existing(membership(manager, lab), **change)])
    assert response.status_code == 200
    assert "A lab needs at least one manager." in response.content.decode()
    assert (snapshot(), AuditEvent.objects.count()) == (before, 0)


def test_an_inactive_user_cannot_be_chosen(admin_client: Client, lab: Lab, manager: User) -> None:
    gone = make_user("gone", is_active=False)
    before = snapshot()
    rows = [existing(membership(manager, lab)), {"lab": lab.pk, "user": gone.pk, "role": "viewer"}]
    url = reverse("admin:labs_lab_change", args=[lab.pk])
    response = admin_client.post(
        url, {"name": lab.name, "code": lab.code, **inline(rows, initial=1)}
    )
    assert response.status_code == 200
    assert "Select a valid choice" in response.content.decode()
    assert snapshot() == before


def test_the_user_of_a_membership_cannot_be_changed(
    admin_client: Client, lab: Lab, manager: User, viewer: User, stranger: User
) -> None:
    rows = [existing(membership(manager, lab)), existing(membership(viewer, lab), user=stranger.pk)]
    response = change_lab(admin_client, lab, rows)
    assert response.status_code == 302, response.content
    assert membership(viewer, lab).role == Role.VIEWER
    assert not Membership.objects.filter(user=stranger).exists()


def test_labs_cannot_be_deleted(admin_client: Client, lab: Lab) -> None:
    response = admin_client.post(reverse("admin:labs_lab_delete", args=[lab.pk]), {"post": "yes"})
    assert response.status_code == 403
    assert Lab.objects.filter(pk=lab.pk).exists()


def test_a_lab_manager_without_staff_status_cannot_use_admin(lab: Lab, manager: User) -> None:
    response = logged_in(manager).get(reverse("admin:labs_lab_changelist"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_admin_renders_the_lab_with_its_members(
    admin_client: Client, lab: Lab, viewer: User
) -> None:
    member_of(lab, Role.MANAGER, "boss")
    response = admin_client.get(reverse("admin:labs_lab_change", args=[lab.pk]))
    assert response.status_code == 200
    assert response.content.decode().count(f'name="{PREFIX}-') > 0

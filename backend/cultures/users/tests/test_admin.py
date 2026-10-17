"""Staff manage users in Django admin, and every save goes through the audited services."""

from typing import Any

import pytest
from django.contrib import admin
from django.test import Client, RequestFactory
from django.urls import reverse

from cultures.audit.models import AuditEvent, Channel, RowChange
from cultures.users.admin import REASON_REQUIRED
from cultures.users.models import User

from .conftest import PASSWORD, make_user, trail

pytestmark = pytest.mark.django_db
NEW_PASSWORD = "a brand new admin password"  # noqa: S105 (a test password)


def change_url(user: User) -> str:
    return reverse("admin:users_user_change", args=[user.pk])


def form_of(user: User, **changes: Any) -> dict[str, Any]:
    """The change form as the browser posts it: unchecked boxes are absent."""
    data: dict[str, Any] = {
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        **{flag: "on" for flag in ("is_active", "is_staff", "is_superuser") if getattr(user, flag)},
    }
    for key, value in changes.items():
        if value is False:
            data.pop(key, None)
        else:
            data[key] = "on" if value is True else value
    return data


def joined(event: AuditEvent) -> list[RowChange]:
    return list(RowChange.objects.filter(txid=event.txid, request_id=event.request_id))


def post_change(client: Client, user: User, request_id: str = "adm-1", **changes: Any) -> Any:
    return client.post(
        change_url(user), form_of(user, **changes), headers={"X-Request-ID": request_id}
    )


def test_an_admin_edit_records_the_staff_actor_and_request_id_on_both_layers(
    admin_client: Client, staff: User, member: User
) -> None:
    response = post_change(admin_client, member, request_id="adm-edit", first_name="Augusta")
    assert response.status_code == 302, response.content

    (event,) = AuditEvent.objects.all()
    assert (event.event_type, event.actor, event.channel, event.request_id) == (
        "user_changed",
        staff,
        Channel.WEB,
        "adm-edit",
    )
    assert event.changes == {"first_name": ["Ada", "Augusta"]}
    # The row trigger's row joins the event by transaction id and request id. (A test runs in
    # one transaction, so the fixtures' rows share the txid and only both ids pick the row.)
    (row,) = joined(event)
    assert (row.op, row.table_label, row.row_pk) == ("UPDATE", "users.user", str(member.pk))
    assert (row.actor_id, row.request_id) == (staff.pk, "adm-edit")
    assert row.new == {"first_name": "Augusta"}


def test_a_save_without_changes_records_nothing(admin_client: Client, member: User) -> None:
    before = trail()
    response = post_change(admin_client, member)
    assert response.status_code == 302, response.content
    assert trail() == before


@pytest.mark.parametrize(
    "change", [{"is_staff": True}, {"is_superuser": True}, {"is_active": False}]
)
@pytest.mark.parametrize("reason", ["", "   "])
def test_a_privilege_change_needs_a_reason(
    change: dict[str, Any], reason: str, admin_client: Client, member: User
) -> None:
    before = (list(User.objects.values()), trail())
    response = post_change(admin_client, member, reason=reason, **change)
    assert response.status_code == 200
    assert REASON_REQUIRED in response.content.decode()
    assert (list(User.objects.values()), trail()) == before


def test_a_profile_edit_needs_no_reason(admin_client: Client, member: User) -> None:
    response = post_change(admin_client, member, email="ada@example.org")
    assert response.status_code == 302, response.content


@pytest.mark.parametrize(
    ("field", "event_type"),
    [
        ("is_staff", "user_staff_changed"),
        ("is_superuser", "user_superuser_changed"),
        ("is_active", "user_deactivated"),
    ],
)
def test_each_privilege_change_is_its_own_event_with_the_reason(
    field: str, event_type: str, admin_client: Client, staff: User, member: User
) -> None:
    old = getattr(member, field)
    change: dict[str, Any] = {field: not old}
    response = post_change(admin_client, member, reason="ticket 42", **change)
    assert response.status_code == 302, response.content

    (event,) = AuditEvent.objects.all()
    assert (event.event_type, event.actor, event.reason, event.changes) == (
        event_type,
        staff,
        "ticket 42",
        {field: [old, not old]},
    )
    member.refresh_from_db()
    assert getattr(member, field) is (not old)


def test_reactivation_is_an_event_with_the_reason(admin_client: Client) -> None:
    gone = make_user("gone", is_active=False)
    response = post_change(admin_client, gone, reason="back from leave", is_active=True)
    assert response.status_code == 302, response.content
    assert [(e.event_type, e.reason) for e in AuditEvent.objects.all()] == [
        ("user_activated", "back from leave")
    ]


def test_profile_and_privileges_in_one_save_share_the_transaction(
    admin_client: Client, member: User
) -> None:
    response = post_change(
        admin_client, member, reason="new admin", email="ada@example.org", is_staff=True
    )
    assert response.status_code == 302, response.content
    recorded = list(AuditEvent.objects.order_by("pk"))
    assert [e.event_type for e in recorded] == ["user_changed", "user_staff_changed"]
    assert len({e.txid for e in recorded}) == 1


def test_users_cannot_be_deleted(admin_client: Client, member: User, staff: User) -> None:
    url = reverse("admin:users_user_delete", args=[member.pk])
    assert admin_client.get(url).status_code == 403
    assert admin_client.post(url, {"post": "yes"}).status_code == 403
    request = RequestFactory().get("/")
    request.user = staff
    assert "delete_selected" not in admin.site._registry[User].get_actions(request)
    response = admin_client.post(
        reverse("admin:users_user_changelist"),
        {"action": "delete_selected", "_selected_action": [member.pk], "post": "yes"},
    )
    assert response.status_code in {200, 302}
    assert User.objects.filter(pk=member.pk).exists()


def test_date_joined_is_read_only(admin_client: Client, member: User) -> None:
    joined = member.date_joined
    response = post_change(
        admin_client, member, date_joined_0="2000-01-01", date_joined_1="00:00:00"
    )
    assert response.status_code == 302, response.content
    member.refresh_from_db()
    assert member.date_joined == joined
    assert not RowChange.objects.filter(row_pk=str(member.pk), op="UPDATE").exists()


def test_the_change_form_offers_the_reason_but_no_groups_or_permissions(
    admin_client: Client, member: User
) -> None:
    page = admin_client.get(change_url(member)).content.decode()
    assert 'name="reason"' in page
    assert 'name="groups"' not in page
    assert 'name="user_permissions"' not in page
    assert 'name="date_joined' not in page


def test_staff_add_a_user_through_user_create(admin_client: Client, staff: User) -> None:
    response = admin_client.post(
        reverse("admin:users_user_add"),
        {
            "username": "newbie",
            "usable_password": "true",
            "password1": NEW_PASSWORD,
            "password2": NEW_PASSWORD,
        },
        headers={"X-Request-ID": "adm-add"},
    )
    assert response.status_code == 302, response.content
    newbie = User.objects.get(username="newbie")
    assert newbie.check_password(NEW_PASSWORD)
    (event,) = AuditEvent.objects.all()
    assert (event.event_type, event.actor, event.request_id, event.subject_id) == (
        "user_created",
        staff,
        "adm-add",
        newbie.public_id,
    )
    (row,) = joined(event)
    assert (row.op, row.actor_id, row.request_id) == ("INSERT", staff.pk, "adm-add")


def test_staff_add_a_user_without_a_usable_password(admin_client: Client) -> None:
    response = admin_client.post(
        reverse("admin:users_user_add"), {"username": "sso", "usable_password": "false"}
    )
    assert response.status_code == 302, response.content
    assert not User.objects.get(username="sso").has_usable_password()


def password_url(user: User) -> str:
    return reverse("admin:auth_user_password_change", args=[user.pk])


def test_the_password_form_saves_through_user_set_password(
    admin_client: Client, staff: User, member: User
) -> None:
    response = admin_client.post(
        password_url(member),
        {"usable_password": "true", "password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
        headers={"X-Request-ID": "adm-pw"},
    )
    assert response.status_code == 302, response.content
    member.refresh_from_db()
    assert member.check_password(NEW_PASSWORD)
    (event,) = AuditEvent.objects.all()
    assert (event.event_type, event.actor, event.channel, event.request_id) == (
        "user_password_changed",
        staff,
        Channel.WEB,
        "adm-pw",
    )
    (row,) = joined(event)
    assert (row.new, row.actor_id, row.request_id) == ({"password": "redacted"}, staff.pk, "adm-pw")


def test_the_password_form_can_disable_password_sign_in(admin_client: Client, member: User) -> None:
    member.set_password(PASSWORD)
    member.save()
    response = admin_client.post(
        password_url(member), {"usable_password": "false", "unset-password": "1"}
    )
    assert response.status_code == 302, response.content
    member.refresh_from_db()
    assert not member.has_usable_password()
    (event,) = AuditEvent.objects.all()
    assert event.changes == {"has_usable_password": [True, False]}


def test_a_member_without_staff_status_cannot_use_the_user_admin(member: User) -> None:
    client = Client()
    client.force_login(member)
    response = client.get(reverse("admin:users_user_changelist"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]

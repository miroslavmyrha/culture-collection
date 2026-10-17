"""Both audit layers for membership changes made through the API.

The service event says what happened and why; the row trigger on labs_membership
records the row itself. Both carry the request's X-Request-ID and actor, and
share the transaction id, so a row change without its event stands out.
"""

from typing import Any

import pytest

from cultures.audit.models import AuditEvent, RowChange
from cultures.core.testing import logged_in
from cultures.labs.models import Lab, Membership
from cultures.users.models import User

from .conftest import MEMBERS_URL, membership

pytestmark = pytest.mark.django_db


def rows(label: str = "labs.membership") -> list[Any]:
    """Typed Any: old and new are JSON, the tests index into them."""
    return list(RowChange.objects.filter(table_label=label).order_by("pk"))


def send(manager: User, method: str, url: str, body: dict[str, str] | None) -> Any:
    return getattr(logged_in(manager), method)(
        url, body, content_type="application/json", headers={"X-Request-ID": "req-42"}
    )


def test_adding_a_member_leaves_an_event_and_an_insert_row_of_one_transaction(
    lab: Lab, manager: User, stranger: User
) -> None:
    before = len(rows())  # the fixtures' memberships wrote rows too
    response = send(manager, "post", MEMBERS_URL, {"username": "stranger", "role": "viewer"})
    added = Membership.objects.get(public_id=response.json()["public_id"])

    event = AuditEvent.objects.get()
    (row,) = rows()[before:]
    assert (event.event_type, event.request_id, event.actor, event.lab) == (
        "member_added",
        "req-42",
        manager,
        lab,
    )
    assert (row.op, row.row_pk, row.actor_id, row.request_id, row.txid) == (
        "INSERT",
        str(added.pk),
        manager.pk,
        "req-42",
        event.txid,
    )
    assert (row.new["user_id"], row.new["lab_id"], row.new["role"]) == (
        stranger.pk,
        lab.pk,
        "viewer",
    )


def test_a_role_change_leaves_an_update_row_with_only_the_role_and_time(
    lab: Lab, manager: User, technician: User
) -> None:
    target = membership(technician, lab)
    before = len(rows())
    send(manager, "patch", f"{MEMBERS_URL}{target.public_id}/", {"role": "curator"})

    (row,) = rows()[before:]
    assert (row.op, row.row_pk, row.request_id, row.txid) == (
        "UPDATE",
        str(target.pk),
        "req-42",
        AuditEvent.objects.get().txid,
    )
    assert set(row.new) == {"role", "updated_at"}
    assert (row.old["role"], row.new["role"]) == ("technician", "curator")


def test_removing_a_member_leaves_a_delete_row_with_the_whole_row(
    lab: Lab, manager: User, viewer: User
) -> None:
    target = membership(viewer, lab)
    before = len(rows())
    send(manager, "delete", f"{MEMBERS_URL}{target.public_id}/", None)

    (row,) = rows()[before:]
    assert (row.op, row.row_pk, row.new, row.request_id) == (
        "DELETE",
        str(target.pk),
        None,
        "req-42",
    )
    assert (row.old["user_id"], row.old["role"], row.old["public_id"]) == (
        viewer.pk,
        "viewer",
        str(target.public_id),
    )
    assert AuditEvent.objects.get().txid == row.txid


def test_a_refused_change_leaves_no_row_change_and_no_event(lab: Lab, manager: User) -> None:
    before = len(rows())
    response = send(manager, "delete", f"{MEMBERS_URL}{membership(manager, lab).public_id}/", None)
    assert response.status_code == 422  # the last manager
    assert (len(rows()), AuditEvent.objects.count()) == (before, 0)


def test_lab_rows_are_audited_too(lab: Lab) -> None:
    (row,) = rows("labs.lab")
    assert (row.op, row.row_pk, row.new["code"], row.actor_id) == (
        "INSERT",
        str(lab.pk),
        "MYC",
        None,
    )

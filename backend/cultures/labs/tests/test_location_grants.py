"""The location grant (ADR 0009, amendment of 2026-10-19): a manager lets a member see where the
lab's regulated strains are stored, and revokes it, each with a reason and an event. Part of no
role. The table holds the history on its own: one open grant per person and lab, revoked once,
never deleted, and the runtime role has no DELETE."""

from collections.abc import Callable
from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction
from django.db.backends.utils import CursorWrapper

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent, RowChange
from cultures.audit.tests.conftest import refused as refused_sql
from cultures.core.exceptions import DomainError, Forbidden, NotFound, RuleViolation
from cultures.core.testing import ViewsetContract, assert_problem, logged_in
from cultures.labs import services
from cultures.labs.access import access_for
from cultures.labs.api.views import LocationGrantViewSet
from cultures.labs.models import Lab, LocationGrant, Membership
from cultures.labs.permissions import Role
from cultures.users.models import User

from .conftest import LAB_URL, member_of, membership

pytestmark = pytest.mark.django_db
GRANTS_URL = f"{LAB_URL}location-grants/"


def snapshot() -> tuple[Any, ...]:
    return (
        list(LocationGrant.objects.order_by("pk").values()),
        AuditEvent.objects.count(),
        RowChange.objects.count(),
    )


def refused(
    error: type[DomainError], code: str, call: Callable[[], object], attr: str | None = None
) -> None:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == (code, attr)
    assert snapshot() == before


def add(
    manager: User, lab: Lab, user: User, reason: str = "keeps the SÚJB register"
) -> LocationGrant:
    return services.location_grant_add(
        access=access_for(manager), lab=lab, membership=membership(user, lab), reason=reason
    )


# Services.


def test_a_manager_grants_and_revokes_with_reasons_and_events(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    granted = add(manager, lab, viewer, "  keeps the register ")
    assert (granted.user, granted.granted_by, granted.reason, granted.revoked_at) == (
        viewer,
        manager,
        "keeps the register",
        None,
    )
    assert services.holds_location_grant(lab_id=lab.pk, user=viewer) is True
    event = AuditEvent.objects.order_by("-pk").first()
    assert event is not None
    assert (event.event_type, event.actor, event.lab_id, event.reason, event.subject_id) == (
        "location_grant_added",
        manager,
        lab.pk,
        "keeps the register",
        granted.public_id,
    )
    assert event.changes == {"user": [None, str(viewer.public_id)]}
    services.location_grant_revoke(access=access_for(manager), grant=granted, reason="moved on")
    granted.refresh_from_db()
    assert (granted.revoked_by, granted.revoke_reason) == (manager, "moved on")
    assert granted.revoked_at is not None
    assert services.holds_location_grant(lab_id=lab.pk, user=viewer) is False
    last = AuditEvent.objects.order_by("-pk").first()
    assert last is not None
    assert (last.event_type, last.reason) == ("location_grant_revoked", "moved on")
    # A new grant is a new row; the old one stays.
    add(manager, lab, viewer)
    assert LocationGrant.objects.filter(user=viewer).count() == 2


def test_a_manager_may_hold_it_too(as_manager: AuditContext, manager: User, lab: Lab) -> None:
    add(manager, lab, manager)
    assert services.holds_location_grant(lab_id=lab.pk, user=manager) is True


def test_a_second_open_grant_is_refused(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    add(manager, lab, viewer)
    refused(services.GrantExists, "already_granted", lambda: add(manager, lab, viewer), "member")


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_only_a_manager_grants(
    as_manager: AuditContext, team: dict[Role, User], lab: Lab, viewer: User, role: Role
) -> None:
    refused(Forbidden, "permission_denied", lambda: add(team[role], lab, viewer))


def test_a_manager_demoted_since_the_request_began_is_refused(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    access = access_for(manager)
    member_of(lab, Role.MANAGER, "second")
    Membership.objects.filter(user=manager, lab=lab).update(role=Role.CURATOR)
    refused(
        Forbidden,
        "permission_denied",
        lambda: services.location_grant_add(
            access=access, lab=lab, membership=membership(viewer, lab), reason="r"
        ),
    )


def test_a_reason_is_required_both_ways(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    refused(RuleViolation, "reason_required", lambda: add(manager, lab, viewer, " "), "reason")
    granted = add(manager, lab, viewer)
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.location_grant_revoke(
            access=access_for(manager), grant=granted, reason=""
        ),
        "reason",
    )


def test_a_grant_is_revoked_once(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    granted = add(manager, lab, viewer)
    services.location_grant_revoke(access=access_for(manager), grant=granted, reason="done")
    refused(
        services.GrantRevoked,
        "grant_revoked",
        lambda: services.location_grant_revoke(
            access=access_for(manager), grant=granted, reason="again"
        ),
    )


def test_a_membership_of_another_lab_is_unknown(
    as_manager: AuditContext, manager: User, lab: Lab, outsider: User, other_lab: Lab
) -> None:
    refused(
        services.UnknownMember,
        "does_not_exist",
        lambda: services.location_grant_add(
            access=access_for(manager),
            lab=lab,
            membership=membership(outsider, other_lab),
            reason="r",
        ),
        "member",
    )


def test_removing_the_member_revokes_the_grant_in_the_same_transaction(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    add(manager, lab, viewer)
    services.member_remove(access=access_for(manager), membership=membership(viewer, lab))
    grant = LocationGrant.objects.get(user=viewer)
    assert (grant.revoke_reason, grant.revoked_by) == ("The member left the lab.", manager)
    types = list(AuditEvent.objects.order_by("-pk").values_list("event_type", flat=True)[:2])
    assert types == ["member_removed", "location_grant_revoked"]


def test_holding_needs_an_active_account_and_a_membership(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    add(manager, lab, viewer)
    User.objects.filter(pk=viewer.pk).update(is_active=False)
    assert services.holds_location_grant(lab_id=lab.pk, user=viewer) is False
    User.objects.filter(pk=viewer.pk).update(is_active=True)
    Membership.objects.filter(user=viewer).delete()  # past the service: the grant stays open
    assert services.holds_location_grant(lab_id=lab.pk, user=viewer) is False


# The table on its own.


def test_one_open_grant_per_person_and_lab(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    add(manager, lab, viewer)
    with pytest.raises(IntegrityError, match="labs_locationgrant_one_open"), transaction.atomic():
        LocationGrant.objects.create(lab=lab, user=viewer, granted_by=manager, reason="again")


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"reason": " "}, "labs_locationgrant_reason_given"),
        ({"revoke_reason": "why"}, "labs_locationgrant_revocation_complete"),
    ],
)
def test_the_database_refuses_a_bad_grant(
    manager: User, lab: Lab, viewer: User, fields: dict[str, Any], constraint: str
) -> None:
    values = {"lab": lab, "user": viewer, "granted_by": manager, "reason": "r", **fields}
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        LocationGrant.objects.create(**values)


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("UPDATE labs_locationgrant SET reason = 'other'", "changes only once"),
        ("UPDATE labs_locationgrant SET user_id = granted_by_id", "changes only once"),
        ("DELETE FROM labs_locationgrant", "never deleted"),
    ],
)
def test_a_grant_changes_only_when_revoked_and_is_never_deleted(
    *, as_manager: AuditContext, manager: User, lab: Lab, viewer: User, statement: str, message: str
) -> None:
    add(manager, lab, viewer)
    with (
        pytest.raises((IntegrityError, InternalError), match=message),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(statement)


def test_a_revoked_grant_never_changes_again(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    granted = add(manager, lab, viewer)
    services.location_grant_revoke(access=access_for(manager), grant=granted, reason="done")
    with (
        pytest.raises((IntegrityError, InternalError), match="changes only once"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE labs_locationgrant SET revoked_at = NULL, revoked_by_id = NULL,"
            " revoke_reason = ''"
        )


def test_the_runtime_role_grants_and_revokes_but_deletes_nothing(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User, runtime_role: CursorWrapper
) -> None:
    granted = add(manager, lab, viewer)
    services.location_grant_revoke(access=access_for(manager), grant=granted, reason="done")
    refused_sql(runtime_role, "DELETE FROM labs_locationgrant", "permission denied")


# The API.


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_only_managers_see_and_change_the_grants(
    *,
    role: Role,
    team: dict[Role, User],
    manager: User,
    lab: Lab,
    viewer: User,
    as_manager: AuditContext,
) -> None:
    granted = add(manager, lab, viewer)
    client = logged_in(team[role])
    before = snapshot()
    # A list they may not read is a 403, a single grant is not even found (deposits do the same).
    assert_problem(client.get(GRANTS_URL), 403, "permission_denied")
    assert_problem(client.get(f"{GRANTS_URL}{granted.public_id}/"), 404, "not_found")
    body = {"member": "x", "reason": ""}  # invalid on purpose: 403 comes before the input
    assert_problem(
        client.post(GRANTS_URL, body, content_type="application/json"), 403, "permission_denied"
    )
    revoke = f"{GRANTS_URL}{granted.public_id}/revoke/"
    assert_problem(client.post(revoke, {}, content_type="application/json"), 404, "not_found")
    assert snapshot() == before


def test_outsiders_and_anonymous_get_404_and_401(
    outsider: User, manager: User, lab: Lab, viewer: User, as_manager: AuditContext
) -> None:
    granted = add(manager, lab, viewer)
    for url in (GRANTS_URL, f"{GRANTS_URL}{granted.public_id}/"):
        assert_problem(logged_in(outsider).get(url), 404, "not_found")
        assert_problem(logged_in(None).get(url), 401, "not_authenticated")
    response = logged_in(outsider).post(GRANTS_URL, {}, content_type="application/json")
    assert_problem(response, 404, "not_found")


def test_a_manager_grants_lists_and_revokes_through_the_api(
    manager: User, lab: Lab, curator: User
) -> None:
    client = logged_in(manager)
    member = membership(curator, lab)
    created = client.post(
        GRANTS_URL,
        {"member": str(member.public_id), "reason": "keeps the register"},
        content_type="application/json",
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert (body["member"], body["username"], body["reason"]) == (
        str(member.public_id),
        "curator",
        "keeps the register",
    )
    listed = client.get(GRANTS_URL).json()
    assert [row["username"] for row in listed] == ["curator"]
    again = client.post(
        GRANTS_URL,
        {"member": str(member.public_id), "reason": "twice"},
        content_type="application/json",
    )
    assert_problem(again, 400, "already_granted", "member")
    revoked = client.post(
        f"{GRANTS_URL}{body['public_id']}/revoke/",
        {"reason": "moved on"},
        content_type="application/json",
    )
    assert revoked.status_code == 204
    assert client.get(GRANTS_URL).json() == []
    # A revoked grant is not found any more: the list and the detail hold the open ones.
    assert_problem(client.get(f"{GRANTS_URL}{body['public_id']}/"), 404, "not_found")


def test_a_member_of_another_lab_is_an_unknown_member(
    manager: User, lab: Lab, other_lab: Lab, outsider: User
) -> None:
    Membership.objects.create(user=manager, lab=other_lab, role=Role.MANAGER)
    elsewhere = membership(outsider, other_lab)
    before = snapshot()
    response = logged_in(manager).post(
        GRANTS_URL,
        {"member": str(elsewhere.public_id), "reason": "r"},
        content_type="application/json",
    )
    assert_problem(response, 400, "does_not_exist", "member")
    assert snapshot() == before


class TestLocationGrantContract(ViewsetContract):
    """Only managers read and write grants, so no role reads without writing: the refused
    writes per role are in test_only_managers_see_and_change_the_grants above."""

    viewset = LocationGrantViewSet
    url = GRANTS_URL
    writes = ()

    @pytest.fixture
    def obj(self, manager: User, lab: Lab, viewer: User, as_manager: AuditContext) -> LocationGrant:
        return add(manager, lab, viewer)

    @pytest.fixture
    def reader(self, manager: User) -> User:
        return manager

    @pytest.fixture
    def writer(self, manager: User) -> User:
        return manager

    # Not paged, and nested under a lab the outsider is not a member of: a 404 for all of it.
    def test_list_is_scoped(self, obj: LocationGrant, reader: User, outsider: User) -> None:
        listed = logged_in(reader).get(self.url).json()
        assert str(obj.public_id) in [row["public_id"] for row in listed]
        assert_problem(logged_in(outsider).get(self.url), 404, "not_found")


def test_no_grant_object_is_found_from_the_wrong_lab(
    manager: User, lab: Lab, viewer: User, as_manager: AuditContext
) -> None:
    granted = add(manager, lab, viewer)
    with pytest.raises(NotFound):
        services.location_grant_revoke(
            access=access_for(manager),
            grant=LocationGrant(pk=granted.pk + 1000, lab_id=lab.pk),
            reason="r",
        )

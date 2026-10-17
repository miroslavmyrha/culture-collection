"""Services: the grant rules, the audit event of every write, nothing written on a refusal."""

from typing import Any

import pytest

from cultures.audit.context import AuditContext, MissingAuditContext
from cultures.audit.models import ActorKind, AuditEvent, Channel
from cultures.core.exceptions import Forbidden, NotFound
from cultures.core.testing import run_before
from cultures.labs import services
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import ROLE_PERMS, Perm, Role
from cultures.labs.services import (
    AlreadyMember,
    DuplicateLab,
    GrantAboveOwnRole,
    LastManager,
    UnknownUser,
)
from cultures.users.models import User

from .conftest import make_user, member_of, membership, snapshot

pytestmark = pytest.mark.django_db


def only_event() -> AuditEvent:
    event: AuditEvent = AuditEvent.objects.get()
    return event


def event_fields(event: AuditEvent) -> dict[str, Any]:
    return {
        "event_type": event.event_type,
        "actor": event.actor,
        "actor_kind": event.actor_kind,
        "channel": event.channel,
        "request_id": event.request_id,
        "lab": event.lab,
        "subject_type": event.subject_type,
        "subject_id": event.subject_id,
        "changes": event.changes,
    }


def by_manager(manager: User, lab: Lab, **fields: Any) -> dict[str, Any]:
    return {
        "actor": manager,
        "actor_kind": ActorKind.USER,
        "channel": Channel.API,
        "request_id": "req-1",
        "lab": lab,
        **fields,
    }


@pytest.fixture
def grant_curators_member_management(monkeypatch: pytest.MonkeyPatch) -> None:
    """A future role map where curators manage members too: the ceiling must still hold."""
    monkeypatch.setitem(ROLE_PERMS, Role.CURATOR, ROLE_PERMS[Role.CURATOR] | {Perm.MANAGE_MEMBERS})


# Adding


def test_a_manager_adds_a_member_and_one_event_says_so(
    lab: Lab, manager: User, manager_access: Access, stranger: User, as_manager: AuditContext
) -> None:
    added = services.member_add(access=manager_access, lab=lab, user=stranger, role=Role.CURATOR)
    assert (added.lab, added.user, added.role) == (lab, stranger, Role.CURATOR)
    assert event_fields(only_event()) == by_manager(
        manager,
        lab,
        event_type="member_added",
        subject_type="membership",
        subject_id=added.public_id,
        changes={"user": [None, str(stranger.public_id)], "role": [None, "curator"]},
    )


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_a_member_below_manager_adds_nobody(
    role: Role, lab: Lab, stranger: User, as_manager: AuditContext
) -> None:
    user = member_of(lab, role, "grantor")
    before = snapshot()
    with pytest.raises(Forbidden) as error:
        services.member_add(access=access_for(user), lab=lab, user=stranger, role=Role.VIEWER)
    assert error.value.code == "permission_denied"
    assert (snapshot(), AuditEvent.objects.count()) == (before, 0)


@pytest.mark.usefixtures("grant_curators_member_management")
def test_a_grant_above_the_own_role_is_refused(
    lab: Lab, curator: User, stranger: User, as_manager: AuditContext
) -> None:
    access = access_for(curator)
    services.member_add(access=access, lab=lab, user=make_user("peer"), role=Role.CURATOR)
    before = snapshot()
    with pytest.raises(GrantAboveOwnRole) as error:
        services.member_add(access=access, lab=lab, user=stranger, role=Role.MANAGER)
    assert (error.value.status_code, error.value.code) == (403, "grant_above_own_role")
    assert (snapshot(), AuditEvent.objects.count()) == (before, 1)


def test_an_inactive_user_cannot_be_added(
    lab: Lab, manager_access: Access, as_manager: AuditContext
) -> None:
    gone = make_user("gone", is_active=False)
    with pytest.raises(UnknownUser) as error:
        services.member_add(access=manager_access, lab=lab, user=gone, role=Role.VIEWER)
    assert (error.value.attr, error.value.code) == ("username", "invalid_user")
    assert not Membership.objects.filter(user=gone).exists()
    assert AuditEvent.objects.count() == 0


def test_a_second_membership_is_refused_on_the_username(
    lab: Lab, manager_access: Access, viewer: User, as_manager: AuditContext
) -> None:
    with pytest.raises(AlreadyMember) as error:
        services.member_add(access=manager_access, lab=lab, user=viewer, role=Role.CURATOR)
    assert (error.value.attr, error.value.code) == ("username", "already_member")
    assert (membership(viewer, lab).role, AuditEvent.objects.count()) == (Role.VIEWER, 0)


def test_a_membership_added_meanwhile_is_caught_by_the_constraint(
    lab: Lab, manager_access: Access, stranger: User, as_manager: AuditContext
) -> None:
    # Someone adds the same user between our checks and our insert: the unique
    # constraint is the final arbiter and the error is the same as the plain duplicate.
    def competitor() -> None:
        Membership.objects.create(user=stranger, lab=lab, role=Role.VIEWER)

    with run_before(services, "_save", competitor), pytest.raises(AlreadyMember):
        services.member_add(access=manager_access, lab=lab, user=stranger, role=Role.CURATOR)
    assert AuditEvent.objects.count() == 0


def test_a_grantor_demoted_after_the_request_began_is_refused(
    lab: Lab, manager: User, stranger: User, as_manager: AuditContext
) -> None:
    access = access_for(manager)  # built when the request started, still says manager
    member_of(lab, Role.MANAGER, "other-manager")
    Membership.objects.filter(user=manager).update(role=Role.VIEWER)
    with pytest.raises(Forbidden):
        services.member_add(access=access, lab=lab, user=stranger, role=Role.VIEWER)
    assert not Membership.objects.filter(user=stranger).exists()


def test_audited_writes_refuse_to_run_without_an_audit_context(
    lab: Lab, manager_access: Access, stranger: User
) -> None:
    with pytest.raises(MissingAuditContext):
        services.member_add(access=manager_access, lab=lab, user=stranger, role=Role.VIEWER)
    assert not Membership.objects.filter(user=stranger).exists()


# Changing roles


def test_a_role_change_records_old_and_new(
    lab: Lab, manager: User, manager_access: Access, technician: User, as_manager: AuditContext
) -> None:
    target = membership(technician, lab)
    changed = services.member_change_role(
        access=manager_access, membership=target, role=Role.CURATOR
    )
    assert membership(technician, lab).role == changed.role == Role.CURATOR
    user = str(technician.public_id)
    assert event_fields(only_event()) == by_manager(
        manager,
        lab,
        event_type="member_role_changed",
        subject_type="membership",
        subject_id=target.public_id,
        changes={"user": [user, user], "role": ["technician", "curator"]},
    )


def test_the_same_role_again_changes_nothing_and_records_nothing(
    lab: Lab, manager_access: Access, technician: User, as_manager: AuditContext
) -> None:
    before = snapshot()
    services.member_change_role(
        access=manager_access, membership=membership(technician, lab), role=Role.TECHNICIAN
    )
    assert (snapshot(), AuditEvent.objects.count()) == (before, 0)


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_the_last_manager_cannot_be_demoted(
    role: Role, lab: Lab, manager: User, manager_access: Access, as_manager: AuditContext
) -> None:
    with pytest.raises(LastManager) as error:
        services.member_change_role(
            access=manager_access, membership=membership(manager, lab), role=role
        )
    assert (error.value.status_code, error.value.code) == (422, "last_manager")
    assert (membership(manager, lab).role, AuditEvent.objects.count()) == (Role.MANAGER, 0)


def test_a_manager_in_another_lab_does_not_count(
    lab: Lab, other_lab: Lab, manager: User, manager_access: Access, as_manager: AuditContext
) -> None:
    Membership.objects.create(user=make_user("elsewhere"), lab=other_lab, role=Role.MANAGER)
    with pytest.raises(LastManager):
        services.member_change_role(
            access=manager_access, membership=membership(manager, lab), role=Role.VIEWER
        )


@pytest.mark.usefixtures("grant_curators_member_management")
def test_nobody_changes_the_role_of_someone_above_them(
    lab: Lab, curator: User, manager: User, as_manager: AuditContext
) -> None:
    member_of(lab, Role.MANAGER, "second-manager")  # so LastManager cannot be the reason
    with pytest.raises(GrantAboveOwnRole):
        services.member_change_role(
            access=access_for(curator), membership=membership(manager, lab), role=Role.VIEWER
        )
    assert membership(manager, lab).role == Role.MANAGER


# Removing


def test_removing_a_member_records_who_and_with_which_role(
    lab: Lab, manager: User, manager_access: Access, viewer: User, as_manager: AuditContext
) -> None:
    target = membership(viewer, lab)
    services.member_remove(access=manager_access, membership=target)
    assert not Membership.objects.filter(pk=target.pk).exists()
    assert event_fields(only_event()) == by_manager(
        manager,
        lab,
        event_type="member_removed",
        subject_type="membership",
        subject_id=target.public_id,
        changes={"user": [str(viewer.public_id), None], "role": ["viewer", None]},
    )


def test_the_last_manager_cannot_be_removed(
    lab: Lab, manager: User, manager_access: Access, as_manager: AuditContext
) -> None:
    with pytest.raises(LastManager):
        services.member_remove(access=manager_access, membership=membership(manager, lab))
    assert (membership(manager, lab).role, AuditEvent.objects.count()) == (Role.MANAGER, 0)


def test_one_of_two_managers_may_leave(
    lab: Lab, manager: User, manager_access: Access, as_manager: AuditContext
) -> None:
    member_of(lab, Role.MANAGER, "stays")
    services.member_remove(access=manager_access, membership=membership(manager, lab))
    assert not Membership.objects.filter(user=manager).exists()


def test_a_membership_removed_meanwhile_is_not_found(
    lab: Lab, manager_access: Access, viewer: User, as_manager: AuditContext
) -> None:
    target = membership(viewer, lab)
    Membership.objects.filter(pk=target.pk).delete()
    with pytest.raises(NotFound):
        services.member_remove(access=manager_access, membership=target)
    assert AuditEvent.objects.count() == 0


# The trusted layer: staff in admin and commands


def test_a_command_creates_a_lab_with_a_system_event(as_system: AuditContext) -> None:
    lab = services.lab_create(name="Virology", code="VIR")
    event = only_event()
    assert (event.event_type, event.actor, event.actor_kind, event.actor_label, event.lab) == (
        "lab_created",
        None,
        ActorKind.SYSTEM,
        "command:test",
        lab,
    )
    assert event.changes == {"name": [None, "Virology"], "code": [None, "VIR"]}


@pytest.mark.parametrize(
    ("name", "code", "attr"), [("mycology", "NEW", "name"), ("New lab", "MYC", "code")]
)
def test_a_duplicate_lab_is_refused_on_its_field(
    name: str, code: str, attr: str, lab: Lab, as_system: AuditContext
) -> None:
    with pytest.raises(DuplicateLab) as error:
        services.lab_create(name=name, code=code)
    assert (error.value.attr, error.value.code) == (attr, "unique")
    assert (Lab.objects.count(), AuditEvent.objects.count()) == (1, 0)


def test_a_lab_update_records_only_what_changed(lab: Lab, as_system: AuditContext) -> None:
    services.lab_update(lab=lab, name="Mycology", code="MYCO")
    services.lab_update(lab=lab, name="Mycology", code="MYCO")  # nothing new: no event
    event = only_event()
    assert (event.event_type, event.changes, event.lab) == (
        "lab_updated",
        {"code": ["MYC", "MYCO"]},
        lab,
    )


def test_staff_add_the_first_manager_of_a_new_lab(stranger: User, as_system: AuditContext) -> None:
    lab = services.lab_create(name="Virology", code="VIR")
    added = services.membership_create(lab=lab, user=stranger, role=Role.MANAGER)
    assert access_for(stranger).can(Perm.MANAGE_MEMBERS, lab.pk)
    assert added.role == Role.MANAGER


def test_the_trusted_layer_keeps_the_last_manager_too(
    lab: Lab, manager: User, as_system: AuditContext
) -> None:
    with pytest.raises(LastManager):
        services.membership_delete(membership=membership(manager, lab))
    with pytest.raises(LastManager):
        services.membership_set_role(membership=membership(manager, lab), role=Role.VIEWER)


def test_the_trusted_layer_refuses_inactive_users(lab: Lab, as_system: AuditContext) -> None:
    with pytest.raises(UnknownUser):
        services.membership_create(
            lab=lab, user=make_user("gone", is_active=False), role=Role.VIEWER
        )

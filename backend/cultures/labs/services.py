"""Every write on labs and memberships. Each one runs in audited_atomic() and records its event.

Two layers, like zulip's check_* and do_*:
- lab_* and membership_* are trusted: staff in Django admin and commands call
  them. They keep the rules that hold for everybody (an active user, one
  membership per user and lab, a lab never loses its last manager) and audit.
- member_* are the lab managers' writes through the API. Under the same lab
  lock they first re-read the grantor's role from the database, then refuse a
  grant above it, and only then call the trusted layer. The viewset already
  answered 403 from the request's access object; the re-check closes the race
  with a concurrent demotion of the grantor.

Lock order: the lab row first, then memberships. Every member change of a lab
takes the lab lock, so "is this the last manager?" is answered on committed
data and two managers cannot demote each other at the same time.
"""

from django.db import IntegrityError, transaction
from django.db.models import Model

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    LAB_CREATED,
    LAB_UPDATED,
    MEMBER_ADDED,
    MEMBER_REMOVED,
    MEMBER_ROLE_CHANGED,
)
from cultures.core.exceptions import DomainError, Forbidden, NotFound, RuleViolation
from cultures.users.models import User

from .access import Access
from .models import LAB_CODE_UNIQUE, LAB_NAME_UNIQUE, MEMBERSHIP_UNIQUE, Lab, Membership
from .permissions import Perm, Role, may_grant, role_has

LAB = "lab"
MEMBERSHIP = "membership"


class DuplicateLab(DomainError):
    default_code = "unique"
    default_detail = "A lab with this value already exists."


class UnknownUser(DomainError):
    """The same error for a username that does not exist and for an inactive user."""

    default_code = "invalid_user"
    default_detail = "No active user with this username."


class AlreadyMember(DomainError):
    default_code = "already_member"
    default_detail = "This user is already a member of the lab."


class LastManager(RuleViolation):
    default_code = "last_manager"
    default_detail = "A lab needs at least one manager."


class GrantAboveOwnRole(Forbidden):
    default_code = "grant_above_own_role"
    default_detail = "You cannot grant or change a role above your own."


def _save(obj: Model, errors: dict[str, DomainError]) -> None:
    """The unique constraints are the final arbiter: a check before saving can race."""
    try:
        with transaction.atomic():  # a savepoint, so the outer transaction stays usable
            obj.save()
    except IntegrityError as exc:
        diag = getattr(exc.__cause__, "diag", None)
        error = errors.get(str(getattr(diag, "constraint_name", "")))
        if error is not None:
            raise error from exc
        raise


def _lock_lab(lab_id: int) -> Lab:
    return Lab.objects.select_for_update().get(pk=lab_id)


def _user_id(user: User) -> str:
    return str(user.public_id)  # pseudonymous: names never go into audit changes


# Labs: staff in admin, commands.


def lab_create(*, name: str, code: str) -> Lab:
    with audited_atomic():
        lab = Lab(name=name, code=code)
        _save(lab, _lab_errors())
        record_event(
            LAB_CREATED,
            Change(LAB, lab.public_id, {"name": [None, name], "code": [None, code]}, lab_id=lab.pk),
        )
    return lab


def lab_update(*, lab: Lab, name: str, code: str) -> Lab:
    with audited_atomic():
        locked = _lock_lab(lab.pk)
        changes = {
            field: [old, new]
            for field, old, new in (("name", locked.name, name), ("code", locked.code, code))
            if old != new
        }
        if not changes:
            return locked
        locked.name, locked.code = name, code
        _save(locked, _lab_errors())
        record_event(LAB_UPDATED, Change(LAB, locked.public_id, changes, lab_id=locked.pk))
    return locked


def _lab_errors() -> dict[str, DomainError]:
    return {
        LAB_NAME_UNIQUE: DuplicateLab("A lab with this name already exists.", attr="name"),
        LAB_CODE_UNIQUE: DuplicateLab("A lab with this code already exists.", attr="code"),
    }


# Memberships, trusted: staff in admin, commands. The rules here hold for everybody.


def membership_create(*, lab: Lab, user: User, role: Role) -> Membership:
    with audited_atomic():
        _lock_lab(lab.pk)
        if not User.objects.filter(pk=user.pk, is_active=True).exists():
            raise UnknownUser(attr="username")
        membership = Membership(lab=lab, user=user, role=role)
        _save(membership, {MEMBERSHIP_UNIQUE: AlreadyMember(attr="username")})
        record_event(
            MEMBER_ADDED,
            Change(
                MEMBERSHIP,
                membership.public_id,
                {"user": [None, _user_id(user)], "role": [None, role]},
                lab_id=lab.pk,
            ),
        )
    return membership


def membership_set_role(*, membership: Membership, role: Role) -> Membership:
    with audited_atomic():
        locked = _locked_membership(membership)
        if locked.role == role:
            return locked
        if locked.role == Role.MANAGER:
            _keep_a_manager(locked)
        old = locked.role
        locked.role = role
        locked.save(update_fields=["role", "updated_at"])
        user = _user_id(locked.user)
        record_event(
            MEMBER_ROLE_CHANGED,
            Change(
                MEMBERSHIP,
                locked.public_id,
                {"user": [user, user], "role": [old, role]},
                lab_id=locked.lab_id,
            ),
        )
    return locked


def membership_delete(*, membership: Membership) -> None:
    with audited_atomic():
        locked = _locked_membership(membership)
        if locked.role == Role.MANAGER:
            _keep_a_manager(locked)
        public_id, lab_id, role = locked.public_id, locked.lab_id, locked.role
        user = _user_id(locked.user)
        locked.delete()
        record_event(
            MEMBER_REMOVED,
            Change(
                MEMBERSHIP, public_id, {"user": [user, None], "role": [role, None]}, lab_id=lab_id
            ),
        )


def _locked_membership(membership: Membership) -> Membership:
    """The lab first, then the row, both locked. Gone in the meantime: NotFound."""
    _lock_lab(membership.lab_id)
    locked = (
        Membership.objects.select_for_update(of=("self",))
        .select_related("user")
        .filter(pk=membership.pk)
        .first()
    )
    if locked is None:
        raise NotFound
    return locked


def _keep_a_manager(membership: Membership) -> None:
    """Caller holds the lab lock, so no other change of this lab's members runs meanwhile."""
    others = Membership.objects.filter(lab_id=membership.lab_id, role=Role.MANAGER).exclude(
        pk=membership.pk
    )
    if not others.exists():
        raise LastManager


# Memberships, checked: a lab manager through the API.


def member_add(*, access: Access, lab: Lab, user: User, role: Role) -> Membership:
    with audited_atomic():
        _lock_lab(lab.pk)
        _check_grant(_grantor_role(access, lab.pk), role)
        return membership_create(lab=lab, user=user, role=role)


def member_change_role(*, access: Access, membership: Membership, role: Role) -> Membership:
    with audited_atomic():
        _lock_lab(membership.lab_id)
        grantor = _grantor_role(access, membership.lab_id)
        _check_grant(grantor, role)
        _check_grant(grantor, _current_role(membership))
        return membership_set_role(membership=membership, role=role)


def member_remove(*, access: Access, membership: Membership) -> None:
    with audited_atomic():
        _lock_lab(membership.lab_id)
        _check_grant(_grantor_role(access, membership.lab_id), _current_role(membership))
        membership_delete(membership=membership)


def _grantor_role(access: Access, lab_id: int) -> Role:
    """The grantor's role as committed now (caller holds the lab lock), not as the request began."""
    role = (
        Membership.objects.filter(lab_id=lab_id, user=access.user, user__is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    if role is None or not role_has(Role(role), Perm.MANAGE_MEMBERS):
        raise Forbidden
    return Role(role)


def _current_role(membership: Membership) -> Role:
    role = Membership.objects.filter(pk=membership.pk).values_list("role", flat=True).first()
    if role is None:
        raise NotFound
    return Role(role)


def _check_grant(grantor: Role, role: Role) -> None:
    """Grant only up to your own role, and touch nobody who outranks you."""
    if not may_grant(grantor, role):
        raise GrantAboveOwnRole

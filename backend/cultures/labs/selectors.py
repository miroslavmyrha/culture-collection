"""Reads. Every one takes the access object, so the lab scope is part of the signature, except
has_vrat_access: a rule that services ask after they checked their caller."""

from datetime import datetime
from uuid import UUID

from django.db.models import F, OuterRef, Q, QuerySet, Subquery

from cultures.core.exceptions import NotFound
from cultures.users.models import User

from .access import Access
from .models import Lab, LocationGrant, Membership, VratAccess
from .permissions import Perm


def lab_list(*, access: Access) -> QuerySet[Lab]:
    """The labs the user is a member of, with their role as `my_role`, by name."""
    my_role = Membership.objects.filter(lab=OuterRef("pk"), user=access.user).values("role")[:1]
    return (
        Lab.objects.for_access(access, Perm.VIEW_LAB)
        .annotate(my_role=Subquery(my_role))
        .order_by("name")
    )


def lab_get(*, access: Access, public_id: str) -> Lab:
    """One lab the user may view. Not a member, missing and malformed ids all raise NotFound."""
    lab = lab_list(access=access).filter(public_id=public_id).first() if _uuid(public_id) else None
    if lab is None:
        raise NotFound
    return lab


def member_list(*, access: Access, lab: Lab) -> QuerySet[Membership]:
    """The members of one lab, by username. Empty unless the user may view its members."""
    return (
        Membership.objects.for_access(access, Perm.VIEW_MEMBERS)
        .filter(lab=lab)
        .select_related("user")
        .order_by("user__username")
    )


def _uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def location_grant_list(*, access: Access, lab: Lab) -> QuerySet[LocationGrant]:
    """The open location grants of one lab, for its managers, by username, each with the
    holder's membership public id (`membership_public_id`)."""
    membership = Membership.objects.filter(lab=OuterRef("lab"), user=OuterRef("user"))
    return (
        LocationGrant.objects.for_access(access, Perm.MANAGE_MEMBERS)
        .filter(lab=lab, revoked_at__isnull=True)
        .select_related("user")
        .annotate(membership_public_id=Subquery(membership.values("public_id")[:1]))
        .order_by("user__username", "pk")
    )


def vrat_access_list(*, access: Access, lab: Lab) -> QuerySet[VratAccess]:
    """The lab's VRAT access list with its history (act 281/2002 Sb., § 14a(4)), for its
    managers: the open entries by username, then the ended ones, the latest end first. An
    erased person reads as their tombstone username (erased-<public_id>) at read time."""
    return (
        VratAccess.objects.for_access(access, Perm.MANAGE_MEMBERS)
        .filter(lab=lab)
        .select_related("user", "granted_by", "ended_by")
        .order_by(F("ended_at").desc(nulls_first=True), "user__username", "pk")
    )


def has_vrat_access(*, user: User, lab: Lab, at: datetime) -> bool:
    """Whether the user was on the lab's VRAT access list at the moment `at`: an entry put on it
    at or before `at` and not ended by then (ended_at after `at`). The list's own history, so it
    answers for a past moment too. An entry ends when its holder leaves the lab or is deactivated
    or erased (the services, and the guards of labs 0006 at commit), so an open entry is always
    an active member's. A service that decides on the present holds the lab lock, so an ending
    at the same moment is seen in full."""
    return (
        VratAccess.objects.filter(lab=lab, user=user, created_at__lte=at)
        .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=at))
        .exists()
    )

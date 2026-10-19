"""Reads. Every one takes the access object, so the lab scope is part of the signature."""

from uuid import UUID

from django.db.models import OuterRef, QuerySet, Subquery

from cultures.core.exceptions import NotFound

from .access import Access
from .models import Lab, LocationGrant, Membership
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

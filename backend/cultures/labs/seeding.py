"""What seed_dev and seed_e2e make of labs, through the services: labs, memberships and
location grants.

Found again by natural keys, so a second run creates nothing twice: a lab by its code, a
membership by its lab and user (its role set back to the seed's), an open location grant by its
lab and user.
"""

from cultures.users.models import User

from . import services
from .access import access_for
from .models import Lab, LocationGrant, Membership
from .permissions import Role


def lab(name: str, code: str) -> Lab:
    """The lab with this code, as found, or a new one."""
    return Lab.objects.filter(code=code).first() or services.lab_create(name=name, code=code)


def member(lab: Lab, user: User, role: Role) -> None:
    """The user is a member of the lab in this role."""
    membership = Membership.objects.filter(lab=lab, user=user).first()
    if membership is None:
        services.membership_create(lab=lab, user=user, role=role)
    elif membership.role != role:
        services.membership_set_role(membership=membership, role=role)


def no_member(lab: Lab, user: User) -> None:
    """The user is not a member of the lab."""
    for membership in Membership.objects.filter(lab=lab, user=user):
        services.membership_delete(membership=membership)


def location_grant(lab: Lab, user: User, *, granted_by: User, reason: str) -> None:
    """ADR 0009: the member may see where the lab's regulated strains are, granted by a manager.
    An open grant is kept as found."""
    if LocationGrant.objects.filter(lab=lab, user=user, revoked_at__isnull=True).exists():
        return
    services.location_grant_add(
        access=access_for(granted_by),
        lab=lab,
        membership=Membership.objects.get(lab=lab, user=user),
        reason=reason,
    )

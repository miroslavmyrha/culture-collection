"""Lab roles and what each may do, in code (ADR 0006).

Roles are ordered: viewer < technician < curator < manager. Each role has the
permissions of every role below it plus its own, so the map is cumulative by
construction: GRANTS lists only what a role adds.

Enforced today: view the lab and its members, manage members (#9), view strains
and manage them (#11), view and manage depositors and deposits, publish MTA
versions (#10, #12), view and manage storage (#14), handle vials (#16), release
and hold batches (#17). The others are named now so later features plug into the
same map instead of inventing their own checks.
"""

from enum import StrEnum

from django.db import models


class Role(models.TextChoices):
    VIEWER = "viewer"
    TECHNICIAN = "technician"
    CURATOR = "curator"
    MANAGER = "manager"


# Lowest first. The order is the rank: a role outranks every role before it.
ROLES: tuple[Role, ...] = (Role.VIEWER, Role.TECHNICIAN, Role.CURATOR, Role.MANAGER)
RANK: dict[Role, int] = {role: rank for rank, role in enumerate(ROLES)}


class Perm(StrEnum):
    # #9: labs and members
    VIEW_LAB = "labs.view_lab"
    VIEW_MEMBERS = "labs.view_members"
    MANAGE_MEMBERS = "labs.manage_members"
    # #11: strains. Viewing them and their restrictions; creating, reclassifying, changing
    # the risk group or the restrictions.
    VIEW_STRAINS = "strains.view"
    # Later features check these through the same map.
    HANDLE_VIALS = "vials.handle"
    # #14: storage. Viewing the units; adding, changing, moving and retiring them. The tree
    # carries the risk group caps of ADR 0009, so it is the curators' (vials are placed in it
    # by technicians, #15).
    VIEW_STORAGE = "storage.view"
    MANAGE_STORAGE = "storage.manage"
    MANAGE_STRAINS = "strains.manage"  # #11
    # #10 and #12: depositors (with their contacts), deposits and their terms. Reading them
    # shows personal contacts, so it is not a viewer's permission (ADR 0008, 2026-10-19).
    VIEW_DEPOSITS = "deposits.view"
    MANAGE_DEPOSITS = "deposits.manage"
    # Publishing an MTA template version: a legal text the lab signs up to.
    MANAGE_MTA = "deposits.manage_mta"
    MANAGE_DISTRIBUTION = "distribution.manage"
    # #17: releasing a batch for use, or holding it. Recording its checks is bench work
    # (HANDLE_VIALS); deciding on them is the curators' (ADR 0008, D16).
    RELEASE_BATCHES = "batches.release"


# What each role adds to the roles below it.
GRANTS: dict[Role, frozenset[Perm]] = {
    Role.VIEWER: frozenset(
        {Perm.VIEW_LAB, Perm.VIEW_MEMBERS, Perm.VIEW_STRAINS, Perm.VIEW_STORAGE}
    ),
    Role.TECHNICIAN: frozenset({Perm.HANDLE_VIALS}),
    Role.CURATOR: frozenset(
        {
            Perm.MANAGE_STRAINS,
            Perm.MANAGE_STORAGE,
            Perm.VIEW_DEPOSITS,
            Perm.MANAGE_DEPOSITS,
            Perm.MANAGE_DISTRIBUTION,
            Perm.RELEASE_BATCHES,
        }
    ),
    Role.MANAGER: frozenset({Perm.MANAGE_MEMBERS, Perm.MANAGE_MTA}),
}


def _cumulative() -> dict[Role, frozenset[Perm]]:
    perms: dict[Role, frozenset[Perm]] = {}
    held: frozenset[Perm] = frozenset()
    for role in ROLES:
        held |= GRANTS[role]
        perms[role] = held
    return perms


ROLE_PERMS: dict[Role, frozenset[Perm]] = _cumulative()


def role_has(role: Role, perm: Perm) -> bool:
    return perm in ROLE_PERMS[role]


def outranks(role: Role, other: Role) -> bool:
    """True when role is strictly above other."""
    return RANK[role] > RANK[other]


def may_grant(granter: Role, role: Role) -> bool:
    """A member manager grants at most their own role, never above it."""
    return role_has(granter, Perm.MANAGE_MEMBERS) and not outranks(role, granter)

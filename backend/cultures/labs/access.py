"""One access object per request: who the user is and their role in each lab.

Every lab-scoped read and every check goes through it, so the rule lives in
one place. It is built from the database once per request and never cached
across requests: a removed member loses access with the next request.
Inactive users get no labs. There is no superuser or staff shortcut: staff
work in Django admin, the API treats them like everybody else.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from django.http import HttpRequest
from rest_framework.request import Request

from cultures.users.auth import current_user
from cultures.users.models import User

from .models import Membership
from .permissions import Perm, Role, role_has

_REQUEST_ATTR = "_labs_access"


@dataclass(frozen=True)
class Access:
    user: User
    roles: Mapping[int, Role] = field(default_factory=lambda: MappingProxyType({}))

    def role_in(self, lab_id: int) -> Role | None:
        return self.roles.get(lab_id)

    def can(self, perm: Perm, lab_id: int) -> bool:
        role = self.role_in(lab_id)
        return role is not None and role_has(role, perm)

    def labs_with(self, perm: Perm) -> frozenset[int]:
        """Internal ids of the labs where the user has perm: the scope of every lab query."""
        return frozenset(lab_id for lab_id, role in self.roles.items() if role_has(role, perm))


def access_for(user: User) -> Access:
    """The user's roles from the database. Inactive users get none."""
    if not user.is_active:
        return Access(user=user)
    rows = Membership.objects.filter(user=user).values_list("lab_id", "role")
    return Access(user=user, roles=MappingProxyType({lab_id: Role(role) for lab_id, role in rows}))


def access_of(request: Request) -> Access:
    """The request's access object, built on first use and kept on the request."""
    http: HttpRequest = request._request
    access = getattr(http, _REQUEST_ATTR, None)
    if not isinstance(access, Access):
        access = access_for(current_user(request))
        setattr(http, _REQUEST_ATTR, access)
    return access

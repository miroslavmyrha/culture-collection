"""The shared ViewsetContract passes a correct viewset and fails broken ones.

Until an app routes a viewset, this file is the only place the contract runs.
The viewsets here are routed through this module's own URLconf
(pytest.mark.urls), so the project's coverage meta-test never sees them.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth.models import update_last_login
from django.contrib.auth.signals import user_logged_in
from django.db.models import Model, QuerySet
from model_bakery import baker
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from cultures.core.api import ScopedModelViewSet
from cultures.core.testing import COVERED, ViewsetContract, Write
from cultures.users.auth import current_user
from cultures.users.models import User

pytestmark = [pytest.mark.django_db, pytest.mark.urls(__name__)]

PERMS = {
    "list": "view",
    "retrieve": "view",
    "create": "change",
    "update": "change",
    "partial_update": "change",
    "destroy": "change",
}


class UserOut(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ("public_id", "username", "first_name")


class TeamUsers(ScopedModelViewSet):
    """Scope: same last name. change: users whose first name is "writer"."""

    serializer_class = UserOut
    action_perms = PERMS

    def scoped_queryset(self) -> QuerySet[Any]:
        return User.objects.filter(last_name=current_user(self.request).last_name).order_by(
            "username"
        )

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        return perm == "view" or current_user(self.request).first_name == "writer"


class NoScope(TeamUsers):
    def scoped_queryset(self) -> QuerySet[Any]:
        return User.objects.order_by("username")


class WritesBeforeTheCheck(TeamUsers):
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        User.objects.filter(public_id=kwargs["public_id"]).update(first_name="touched")
        return super().partial_update(request, *args, **kwargs)


class AlwaysForbidden(TeamUsers):
    def has_perm(self, perm: str, obj: Model | None) -> bool:
        return perm == "view"


router = SimpleRouter()
router.register("team", TeamUsers, basename="team")
router.register("no-scope", NoScope, basename="no-scope")
router.register("writes-first", WritesBeforeTheCheck, basename="writes-first")
router.register("forbidden", AlwaysForbidden, basename="forbidden")
urlpatterns = router.urls

RENAME = Write(action="", payload={"first_name": "x"}, changes=User, method="patch", status=200)


@pytest.fixture(autouse=True)
def _no_last_login_update() -> Iterator[None]:
    """The writes here snapshot the User table, and the contract logs each user in.

    force_login() fires user_logged_in, whose receiver update_last_login
    (django/contrib/auth/apps.py, Django 6.1) writes users.last_login. Every
    refused write would then seem to change the table.
    """
    user_logged_in.disconnect(dispatch_uid="update_last_login")
    yield
    user_logged_in.connect(update_last_login, dispatch_uid="update_last_login")


@pytest.fixture
def obj() -> User:
    return baker.make(User, username="target", first_name="t", last_name="Alpha")


@pytest.fixture
def reader() -> User:
    return baker.make(User, username="reader", first_name="reader", last_name="Alpha")


@pytest.fixture
def writer() -> User:
    return baker.make(User, username="writer", first_name="writer", last_name="Alpha")


@pytest.fixture
def outsider() -> User:
    # The writer's role in another team: a 404 for it comes from the scope, not the role.
    return baker.make(User, username="outsider", first_name="writer", last_name="Beta")


class TestTeamUsersContract(ViewsetContract):
    viewset = TeamUsers
    url = "/team/"
    writes = (RENAME,)


class NoScopeContract(ViewsetContract):
    viewset = NoScope
    url = "/no-scope/"
    writes = (RENAME,)


class WritesFirstContract(ViewsetContract):
    viewset = WritesBeforeTheCheck
    url = "/writes-first/"
    writes = (RENAME,)


class ForbiddenContract(ViewsetContract):
    viewset = AlwaysForbidden
    url = "/forbidden/"
    writes = (RENAME,)


def test_contract_catches_a_list_without_scope(obj: User, reader: User, outsider: User) -> None:
    with pytest.raises(AssertionError):
        NoScopeContract().test_list_is_scoped(obj, reader, outsider)


def test_contract_catches_a_detail_without_scope(obj: User, reader: User, outsider: User) -> None:
    with pytest.raises(AssertionError):
        NoScopeContract().test_detail_answers_404_outside_the_scope(obj, reader, outsider)


def test_contract_catches_an_outsider_write_without_scope(
    obj: User, outsider: User, reader: User
) -> None:
    # The reader cannot write here, so only the outsider row can fail.
    with pytest.raises(AssertionError, match="404"):
        NoScopeContract().test_refused_writes_change_nothing(obj, reader, outsider)


def test_contract_catches_a_refused_write_that_changed_the_row(
    obj: User, reader: User, outsider: User
) -> None:
    with pytest.raises(AssertionError, match="touched"):
        WritesFirstContract().test_refused_writes_change_nothing(obj, reader, outsider)


def test_contract_catches_a_permitted_write_that_is_refused(obj: User, writer: User) -> None:
    with pytest.raises(AssertionError):
        ForbiddenContract().test_permitted_writes_succeed(obj, writer)


def test_a_contract_class_covers_its_viewset() -> None:
    # The coverage meta-test trusts COVERED: a contract class must register its viewset.
    assert {TeamUsers, NoScope, WritesBeforeTheCheck, AlwaysForbidden} <= COVERED

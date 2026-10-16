"""The scoped viewset guard: structure, 401/403/404 order and ScopedRelatedField."""

from typing import Any

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model, QuerySet
from model_bakery import baker
from rest_framework import permissions, serializers
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from cultures.core.api import (
    AUTHENTICATED,
    STANDARD_ACTIONS,
    ScopedModelViewSet,
    ScopedReadOnlyViewSet,
    ScopedRelatedField,
)
from cultures.core.testing import assert_problem
from cultures.users.models import User

READ_ONLY_PERMS = {"list": AUTHENTICATED, "retrieve": AUTHENTICATED}
ALL_PERMS = {
    "list": "view",
    "retrieve": "view",
    "create": "change",
    "update": "change",
    "partial_update": "change",
    "destroy": "change",
}


# Structure: refused at class creation.


def test_overriding_get_queryset_is_refused() -> None:
    with pytest.raises(TypeError, match="must not override get_queryset"):

        class Leaky(ScopedModelViewSet):
            action_perms = ALL_PERMS

            def get_queryset(self) -> QuerySet[Any]:
                raise AssertionError


def test_a_mixin_placed_before_the_base_cannot_override_get_queryset() -> None:
    class AllRowsMixin:
        def get_queryset(self) -> QuerySet[Any]:
            return User.objects.all()

    with pytest.raises(TypeError, match="must not override get_queryset"):

        class Leaky(AllRowsMixin, ScopedModelViewSet):
            action_perms = ALL_PERMS


@pytest.mark.parametrize(
    "name",
    [
        "get_object",
        "filter_queryset",
        "get_permissions",
        "check_permissions",
        "check_object_permissions",
    ],
)
def test_overriding_permission_plumbing_is_refused(name: str) -> None:
    mixin = type("Mixin", (), {name: lambda self, *args: None})
    with pytest.raises(TypeError, match=f"must not override {name}"):
        type("Leaky", (mixin, ScopedReadOnlyViewSet), {"action_perms": READ_ONLY_PERMS})


def test_permission_classes_are_refused() -> None:
    with pytest.raises(TypeError, match="must not override permission_classes"):

        class Open(ScopedReadOnlyViewSet):
            action_perms = READ_ONLY_PERMS
            permission_classes = (permissions.AllowAny,)


@pytest.mark.parametrize("missing", STANDARD_ACTIONS)
def test_every_action_needs_a_permission(missing: str) -> None:
    perms = {name: perm for name, perm in ALL_PERMS.items() if name != missing}
    with pytest.raises(TypeError, match=rf"no permission for \['{missing}'\]"):
        type("Incomplete", (ScopedModelViewSet,), {"action_perms": perms})


def test_custom_actions_need_a_permission_too() -> None:
    with pytest.raises(TypeError, match=r"no permission for \['archive'\]"):

        class WithAction(ScopedReadOnlyViewSet):
            action_perms = READ_ONLY_PERMS

            @action(detail=True, methods=["post"])
            def archive(self, request: Request, public_id: str) -> Response:
                return Response()


def test_unknown_action_names_are_refused() -> None:
    with pytest.raises(TypeError, match=r"unknown actions \['archve'\]"):

        class Typo(ScopedReadOnlyViewSet):
            action_perms = {**READ_ONLY_PERMS, "archve": "change"}


def test_action_permission_classes_are_refused() -> None:
    with pytest.raises(TypeError, match="ignored here"):

        class WithOpenAction(ScopedReadOnlyViewSet):
            action_perms = {**READ_ONLY_PERMS, "stats": AUTHENTICATED}

            @action(detail=False, permission_classes=[permissions.AllowAny])
            def stats(self, request: Request) -> Response:
                return Response()


def test_abstract_bases_need_no_permissions() -> None:
    class ProjectBase(ScopedModelViewSet, abstract=True):
        pass

    with pytest.raises(TypeError, match="must declare action_perms"):

        class Concrete(ProjectBase):
            pass


# Behaviour: a team-scoped user API. Teams are last names, to stay generic.


class UserOut(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ("public_id", "username", "first_name")


class TeamUsers(ScopedModelViewSet):
    serializer_class = UserOut
    action_perms = {**ALL_PERMS, "stats": "view", "peek": "view"}

    def scoped_queryset(self) -> QuerySet[Any]:
        user = self.request.user
        assert isinstance(user, User)
        return User.objects.filter(last_name=user.last_name).order_by("username")

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        user = self.request.user
        if perm == "view":
            return getattr(user, "first_name", "") != "blocked"
        # change: only your own record
        return obj is not None and obj.pk == getattr(user, "pk", None)

    @action(detail=False)
    def stats(self, request: Request) -> Response:
        return Response({"count": self.get_queryset().count()})

    @action(detail=True)
    def peek(self, request: Request, public_id: str) -> Response:
        return Response({"seen": public_id})  # never loads the object: a bug the base catches


class DenyUnsafe(permissions.BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        return request.method in permissions.SAFE_METHODS


class FrozenTeamUsers(TeamUsers):
    extra_permission_classes = (DenyUnsafe,)


class GlobalPermUsers(ScopedReadOnlyViewSet):
    """No has_perm override: the default asks Django's permission backends."""

    serializer_class = UserOut
    action_perms = {"list": "users.view_user", "retrieve": "users.view_user"}

    def scoped_queryset(self) -> QuerySet[Any]:
        return User.objects.order_by("username")


class ListScope(ScopedReadOnlyViewSet):
    serializer_class = UserOut
    action_perms = READ_ONLY_PERMS

    def scoped_queryset(self) -> QuerySet[Any]:
        return list(User.objects.order_by("pk"))  # type: ignore[return-value]


def run(
    method: str,
    actions: dict[str, Any],
    user: User | None,
    viewset: type[ScopedReadOnlyViewSet | ScopedModelViewSet] = TeamUsers,
    **kwargs: Any,
) -> Response:
    request = getattr(APIRequestFactory(), method)("/x/", kwargs.pop("data", None), format="json")
    if user is not None:
        force_authenticate(request, user=user)
    response: Response = viewset.as_view(actions)(request, **kwargs)
    response.render()
    return response


@pytest.fixture
def me() -> User:
    return baker.make(User, username="me", last_name="Alpha")


@pytest.fixture
def teammate() -> User:
    return baker.make(User, username="mate", last_name="Alpha")


@pytest.fixture
def outsider() -> User:
    return baker.make(User, username="out", last_name="Beta")


@pytest.mark.django_db
class TestScopedViewSet:
    def test_anonymous_gets_401(self, teammate: User) -> None:
        response = run("get", {"get": "retrieve"}, None, public_id=teammate.public_id)
        assert_problem(response, 401, "not_authenticated")
        assert response["WWW-Authenticate"] == 'Session realm="api"'

    def test_list_shows_only_the_scope(self, me: User, teammate: User, outsider: User) -> None:
        response = run("get", {"get": "list"}, me)
        assert response.status_code == 200
        assert [u["username"] for u in response.data["results"]] == ["mate", "me"]

    def test_list_without_the_permission_is_403(self, me: User) -> None:
        me.first_name = "blocked"
        me.save()
        assert_problem(run("get", {"get": "list"}, me), 403, "permission_denied")

    def test_object_outside_the_scope_is_404(self, me: User, outsider: User) -> None:
        response = run("get", {"get": "retrieve"}, me, public_id=outsider.public_id)
        assert_problem(response, 404, "not_found")
        response = run(
            "patch", {"patch": "partial_update"}, me, public_id=outsider.public_id, data={}
        )
        assert_problem(response, 404, "not_found")  # not 403: existence stays hidden

    def test_visible_but_not_permitted_is_403(self, me: User, teammate: User) -> None:
        response = run(
            "patch",
            {"patch": "partial_update"},
            me,
            public_id=teammate.public_id,
            data={"first_name": "x"},
        )
        assert_problem(response, 403, "permission_denied")
        teammate.refresh_from_db()
        assert teammate.first_name != "x"

    def test_permitted_object_action_works(self, me: User) -> None:
        response = run(
            "patch",
            {"patch": "partial_update"},
            me,
            public_id=me.public_id,
            data={"first_name": "M"},
        )
        assert response.status_code == 200
        assert response.data["first_name"] == "M"
        me.refresh_from_db()
        assert me.first_name == "M"

    def test_malformed_id_is_404(self, me: User) -> None:
        response = run("get", {"get": "retrieve"}, me, public_id="not-a-uuid")
        assert_problem(response, 404, "not_found")

    def test_custom_collection_action_uses_the_scope(self, me: User, outsider: User) -> None:
        assert run("get", {"get": "stats"}, me).data == {"count": 1}

    def test_detail_action_that_skips_get_object_fails_loudly(self, me: User) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"without self\.get_object"):
            run("get", {"get": "peek"}, me, public_id=me.public_id)

    def test_options_answers_405_not_a_crash(self, me: User) -> None:
        # DRF routes OPTIONS to the "metadata" action, which has no action_perms entry.
        assert_problem(run("options", {"get": "list"}, me), 405, "method_not_allowed")

    def test_extra_permission_classes_narrow_access(self, me: User) -> None:
        response = run(
            "patch",
            {"patch": "partial_update"},
            me,
            FrozenTeamUsers,
            public_id=me.public_id,
            data={"first_name": "changed"},
        )
        assert_problem(response, 403, "permission_denied")
        me.refresh_from_db()
        assert me.first_name != "changed"

    def test_default_has_perm_refuses_a_user_without_the_django_permission(self, me: User) -> None:
        response = run("get", {"get": "list"}, me, GlobalPermUsers)
        assert_problem(response, 403, "permission_denied")

    def test_default_has_perm_allows_a_user_with_the_django_permission(self, me: User) -> None:
        me.user_permissions.add(Permission.objects.get(codename="view_user"))
        response = run("get", {"get": "list"}, me, GlobalPermUsers)
        assert [row["username"] for row in response.data["results"]] == ["me"]

    def test_scoped_queryset_must_return_a_queryset(self, me: User) -> None:
        with pytest.raises(ImproperlyConfigured, match="must return a QuerySet"):
            run("get", {"get": "list"}, me, ListScope)


# ScopedRelatedField


def active_users(request: Request) -> QuerySet[Any]:
    return User.objects.filter(is_active=True)


class AssignInput(serializers.Serializer[None]):
    assignee = ScopedRelatedField(model=User, scope=active_users)
    reviewers = ScopedRelatedField(model=User, scope=active_users, many=True, required=False)


def validate(data: dict[str, Any]) -> AssignInput:
    request = Request(APIRequestFactory().post("/x/"))
    serializer = AssignInput(data=data, context={"request": request})
    serializer.is_valid()
    return serializer


@pytest.mark.django_db
class TestScopedRelatedField:
    def test_resolves_an_object_in_scope(self) -> None:
        user = baker.make(User, is_active=True)
        serializer = validate({"assignee": str(user.public_id), "reviewers": [str(user.public_id)]})
        assert serializer.validated_data == {"assignee": user, "reviewers": [user]}

    def test_missing_forbidden_and_malformed_ids_get_the_same_error(self) -> None:
        hidden = baker.make(User, is_active=False)
        import uuid  # noqa: PLC0415

        errors = [
            validate({"assignee": value}).errors["assignee"]
            for value in (str(uuid.uuid4()), str(hidden.public_id), "not-a-uuid", 42)
        ]
        assert all(e == ["Invalid user."] for e in errors), errors
        assert {e[0].code for e in errors} == {"does_not_exist"}

    def test_many_checks_every_item(self) -> None:
        visible = baker.make(User, is_active=True)
        hidden = baker.make(User, is_active=False)
        serializer = validate(
            {
                "assignee": str(visible.public_id),
                "reviewers": [str(visible.public_id), str(hidden.public_id)],
            }
        )
        assert serializer.errors["reviewers"] == ["Invalid user."]
        assert serializer.errors["reviewers"][0].code == "does_not_exist"

    def test_needs_the_request(self) -> None:
        user = baker.make(User)
        with pytest.raises(ImproperlyConfigured, match="request"):
            AssignInput(data={"assignee": str(user.public_id)}).is_valid()

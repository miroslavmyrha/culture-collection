"""Base API classes that make object scoping and authorization structural.

A viewset extends ScopedModelViewSet or ScopedReadOnlyViewSet and provides:
- scoped_queryset(): the rows the current user may see. List, detail and
  custom actions all load through it; anything outside answers 404.
- action_perms: a permission name for every action it routes, including
  @action extras. A missing or unknown entry fails at import.
- has_perm(perm, obj): the project's permission check (roles per tenant,
  per lab, ...). The default uses Django's permissions (user.has_perm).

Order of checks: login (401), then for actions without an object
has_perm(perm, None) (403); for detail actions the object is loaded through
scoped_queryset (404 if not visible), then has_perm(perm, obj) (403 if visible
but not permitted). A detail action that never calls self.get_object() fails
loudly instead of running unchecked.

Overriding get_queryset, get_object, get_permissions, check_permissions or
check_object_permissions is refused at class creation, also when the override
comes from a mixin placed before the base: the check resolves each name
through the MRO.
"""

from collections.abc import Callable, Mapping
from typing import Any, ClassVar, cast

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Model, QuerySet
from rest_framework import permissions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

AUTHENTICATED = "authenticated"  # any logged-in user; rows are still scoped
STANDARD_ACTIONS = ("list", "retrieve", "create", "update", "partial_update", "destroy")
DETAIL_ACTIONS = frozenset({"retrieve", "update", "partial_update", "destroy"})
COLLECTION_ACTIONS = frozenset({"list", "create"})

# name -> hint; methods must resolve to ScopedViewSetMixin, attributes to DRF's own class.
PROTECTED = {
    "get_queryset": "implement scoped_queryset() instead",
    "get_object": "use self.get_object() from the base, it is already scoped",
    "get_permissions": "declare action_perms and implement has_perm() instead",
    "check_permissions": "implement has_perm() instead",
    "check_object_permissions": "implement has_perm() instead",
    "permission_classes": "declare action_perms and implement has_perm() instead",
}


PROTECTED_ATTRIBUTES = {"permission_classes": APIView}


def _defining_class(cls: type, name: str) -> type:
    return next(klass for klass in cls.__mro__ if name in vars(klass))


class ActionPermission(permissions.BasePermission):
    """Applies view.action_perms through view.has_perm."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        scoped = cast("ScopedViewSetMixin", view)
        action = scoped.action
        if action is None or action == "metadata":
            return True  # unrouted method: the handler answers 405
        if scoped.is_detail_action():
            return True  # decided per object in get_object()
        return scoped.has_perm(scoped.action_perms[action], None)

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        scoped = cast("ScopedViewSetMixin", view)
        return scoped.has_perm(scoped.action_perms[str(scoped.action)], obj)


class ScopedViewSetMixin(viewsets.GenericViewSet):  # type: ignore[type-arg]
    lookup_field = "public_id"
    action_perms: ClassVar[Mapping[str, str]]
    # Extra checks on top of login and action_perms (they can only narrow access).
    extra_permission_classes: ClassVar[tuple[type[permissions.BasePermission], ...]] = ()
    _object_checked = False

    def __init_subclass__(cls, abstract: bool = False, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name, hint in PROTECTED.items():
            expected = PROTECTED_ATTRIBUTES.get(name, ScopedViewSetMixin)
            if _defining_class(cls, name) is not expected:
                raise TypeError(f"{cls.__name__} must not override {name}: {hint}")
        if abstract:
            return
        declared = getattr(cls, "action_perms", None)
        if not isinstance(declared, Mapping):
            raise TypeError(f"{cls.__name__} must declare action_perms for every action")
        extra = cls.get_extra_actions()
        actions = {name for name in STANDARD_ACTIONS if hasattr(cls, name)}
        actions |= {action.__name__ for action in extra}
        missing = sorted(actions - declared.keys())
        if missing:
            raise TypeError(f"{cls.__name__}.action_perms has no permission for {missing}")
        unknown = sorted(declared.keys() - actions)
        if unknown:
            raise TypeError(f"{cls.__name__}.action_perms names unknown actions {unknown}")
        for action in extra:
            if "permission_classes" in getattr(action, "kwargs", {}):
                raise TypeError(
                    f"{cls.__name__}.{action.__name__}: @action(permission_classes=...) is "
                    "ignored here, declare it in action_perms"
                )

    # The project's hooks.

    def scoped_queryset(self) -> QuerySet[Any]:
        raise NotImplementedError("Return only the rows the current user may see.")

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        """May the current user perform perm (on obj, when given)?

        Override for roles per tenant or per object. The default allows
        AUTHENTICATED and otherwise asks Django's permission backends, which
        deny inactive users and know only global permissions.
        """
        if perm == AUTHENTICATED:
            return True
        user = self.request.user
        return bool(user is not None and user.has_perm(perm))

    # Fixed plumbing.

    def is_detail_action(self) -> bool:
        if self.action in DETAIL_ACTIONS:
            return True
        if self.action in COLLECTION_ACTIONS or self.action is None:
            return False
        return bool(getattr(getattr(self, self.action, None), "detail", False))

    def get_permissions(self) -> list[permissions.BasePermission]:
        return [
            permissions.IsAuthenticated(),
            ActionPermission(),
            *(permission() for permission in self.extra_permission_classes),
        ]

    def check_permissions(self, request: Request) -> None:
        super().check_permissions(request)

    def check_object_permissions(self, request: Request, obj: Any) -> None:
        super().check_object_permissions(request, obj)

    def get_queryset(self) -> QuerySet[Any]:
        if getattr(self, "swagger_fake_view", False):
            # OpenAPI generation runs without a user; give it the model, never data.
            serializer_class: Any = self.get_serializer_class()
            return serializer_class.Meta.model._default_manager.none()  # type: ignore[no-any-return]
        queryset = self.scoped_queryset()
        if not isinstance(queryset, QuerySet):
            raise ImproperlyConfigured(
                f"{type(self).__name__}.scoped_queryset must return a QuerySet"
            )
        return queryset

    def get_object(self) -> Any:
        obj = super().get_object()  # 404 outside the scope, then has_perm
        self._object_checked = True
        return obj

    def finalize_response(
        self, request: Request, response: Response, *args: Any, **kwargs: Any
    ) -> Response:
        if self.is_detail_action() and response.status_code < 400 and not self._object_checked:  # noqa: PLR2004
            raise ImproperlyConfigured(
                f"{type(self).__name__}.{self.action} answered without self.get_object(): "
                "the object permission was never checked"
            )
        return super().finalize_response(request, response, *args, **kwargs)


class ScopedModelViewSet(ScopedViewSetMixin, viewsets.ModelViewSet, abstract=True):  # type: ignore[type-arg]
    pass


class ScopedReadOnlyViewSet(ScopedViewSetMixin, viewsets.ReadOnlyModelViewSet, abstract=True):  # type: ignore[type-arg]
    pass


class ScopedRelatedField(serializers.SlugRelatedField[Any]):
    """A related object in input, referenced by public_id and resolved through a scope.

    `scope(request)` returns the rows the caller may reference, usually the
    same selector the read endpoints use. A missing id, a malformed id and an
    id outside the scope all give the same error, so the field cannot be used
    to probe for objects of other tenants. Works with many=True.

        lab = ScopedRelatedField(model=Lab, scope=lambda request: labs_for(request.user))
    """

    default_error_messages = {"does_not_exist": "Invalid {name}."}

    def __init__(
        self,
        *,
        model: type[Model],
        scope: Callable[[Request], QuerySet[Any]],
        slug_field: str = "public_id",
        **kwargs: Any,
    ) -> None:
        self.scope = scope
        self.model_name = str(model._meta.verbose_name)
        # The base queryset is never queried; it tells the schema generator the model.
        super().__init__(slug_field=slug_field, queryset=model._default_manager.none(), **kwargs)

    def get_queryset(self) -> QuerySet[Any]:
        request = self.context.get("request")
        if request is None:
            raise ImproperlyConfigured(
                "ScopedRelatedField needs the request in the serializer context"
            )
        return self.scope(request)

    def to_internal_value(self, data: Any) -> Any:
        try:
            return self.get_queryset().get(**{self.slug_field: data})
        except (ObjectDoesNotExist, DjangoValidationError, TypeError, ValueError):
            self.fail("does_not_exist", name=self.model_name)


__all__ = [
    "AUTHENTICATED",
    "Model",
    "ScopedModelViewSet",
    "ScopedReadOnlyViewSet",
    "ScopedRelatedField",
]

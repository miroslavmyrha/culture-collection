from functools import cached_property
from typing import Any

from django.db.models import Model, QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from cultures.core.api import AUTHENTICATED, ScopedReadOnlyViewSet
from cultures.core.errors import PROBLEM_CONTENT_TYPE as PROBLEM
from cultures.core.errors import ProblemSerializer
from cultures.labs import selectors as labs
from cultures.labs.access import access_of
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.storage import selectors, services
from cultures.storage.models import StorageUnit, UnitKind, UnitStatus

from .serializers import (
    BoxTypeOutputSerializer,
    UnitCreateInputSerializer,
    UnitDetailOutputSerializer,
    UnitFieldsInputSerializer,
    UnitMoveInputSerializer,
    UnitOutputSerializer,
    UnitStatusInputSerializer,
)

# 401, 403, 404 and 429 with the Problem body are added to every operation by core.schema.
INVALID = OpenApiResponse(
    ProblemSerializer,
    "Invalid input on a field: a parent that may not hold the unit, is inactive or is the unit"
    " itself or below it, a name, slot or barcode taken, a box type on a unit that is no box, or"
    " a box whose positions are occupied",
)
RETIRED = OpenApiResponse(ProblemSerializer, "The unit is retired and changes no more")
RULE = OpenApiResponse(
    ProblemSerializer, "reason_required; unit_not_empty: retire what the unit holds first"
)
LAB_PARAMETER = OpenApiParameter("lab_public_id", OpenApiTypes.UUID, OpenApiParameter.PATH)


# The storage units of one lab, nested under it. The lab comes from the URL and is resolved
# through the caller's labs first: not a member gives 404 for every action, before any role
# check or input validation. Viewers and up read (storage.view), curators and up write
# (storage.manage); the services re-read the role under the lab lock. The list is the whole
# tree of the lab in tree order, not paged: a tree is read whole. Units are never deleted: a
# unit that is gone is retired. (Comments, not a docstring: a docstring becomes the
# description of every operation.)
@extend_schema(parameters=[LAB_PARAMETER])
class StorageUnitViewSet(ScopedReadOnlyViewSet):
    action_perms = {
        "list": Perm.VIEW_STORAGE,
        "retrieve": Perm.VIEW_STORAGE,
        "create": Perm.MANAGE_STORAGE,
        "edit": Perm.MANAGE_STORAGE,
        "move": Perm.MANAGE_STORAGE,
        "set_status": Perm.MANAGE_STORAGE,
    }
    pagination_class = None

    @cached_property
    def lab(self) -> Lab:
        return labs.lab_get(access=access_of(self.request), public_id=self.kwargs["lab_public_id"])

    def get_serializer_class(self) -> type[UnitOutputSerializer]:
        return UnitOutputSerializer if self.action == "list" else UnitDetailOutputSerializer

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.unit_tree(access=access_of(self.request), lab=self.lab)

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        lab_id = obj.lab_id if isinstance(obj, StorageUnit) else self.lab.pk
        return access_of(self.request).can(Perm(perm), lab_id)

    def _detail(self, unit: StorageUnit, status_code: int = status.HTTP_200_OK) -> Response:
        """The unit as committed now, with its breadcrumbs and what it holds."""
        fresh = selectors.unit_tree(access=access_of(self.request), lab=self.lab).get(pk=unit.pk)
        return self._shown(fresh, status_code)

    def _shown(self, unit: StorageUnit, status_code: int = status.HTTP_200_OK) -> Response:
        vars(unit)["ancestors"] = selectors.unit_path(unit)
        vars(unit)["contents"] = list(selectors.unit_children(unit))
        return Response(UnitDetailOutputSerializer(unit).data, status=status_code)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._shown(self.get_object())  # read through the same scoped tree query

    @extend_schema(
        request=UnitCreateInputSerializer,
        responses={201: UnitDetailOutputSerializer, (400, PROBLEM): INVALID},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab  # first: an outsider gets 404, never a 400 that reveals the lab
        data = UnitCreateInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        unit = services.unit_create(
            access=access_of(request),
            lab=lab,
            data=services.NewUnit(
                kind=UnitKind(values["kind"]),
                name=values["name"],
                parent=values["parent"],
                slot=values["slot"],
                barcode=values["barcode"],
                temperature_c=values["temperature_c"],
                max_risk_group=values["max_risk_group"],
                box_type=values["box_type"],
            ),
        )
        return self._detail(unit, status.HTTP_201_CREATED)

    @extend_schema(
        request=UnitFieldsInputSerializer,
        responses={
            200: UnitDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): RETIRED,
        },
    )
    @action(detail=True, methods=["post"], url_path="edit")
    def edit(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        unit: StorageUnit = self.get_object()  # first: 404 or 403 before the input is read
        data = UnitFieldsInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        services.unit_update(
            access=access_of(request),
            unit=unit,
            fields=services.UnitFields(
                name=values["name"],
                barcode=values["barcode"],
                temperature_c=values["temperature_c"],
                max_risk_group=values["max_risk_group"],
                box_type=values["box_type"],
            ),
        )
        return self._detail(unit)

    @extend_schema(
        request=UnitMoveInputSerializer,
        responses={
            200: UnitDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): RETIRED,
        },
    )
    @action(detail=True, methods=["post"], url_path="move")
    def move(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        unit: StorageUnit = self.get_object()
        data = UnitMoveInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        services.unit_move(
            access=access_of(request),
            unit=unit,
            parent=data.validated_data["parent"],
            slot=data.validated_data["slot"],
        )
        return self._detail(unit)

    @extend_schema(
        request=UnitStatusInputSerializer,
        responses={
            200: UnitDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): RETIRED,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        unit: StorageUnit = self.get_object()
        data = UnitStatusInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.unit_set_status(
            access=access_of(request),
            unit=unit,
            status=UnitStatus(data.validated_data["status"]),
            reason=data.validated_data["reason"],
        )
        return self._detail(unit)


# The global box types, read only: every signed-in user reads them, staff add and rename them
# in admin. Nothing lab-scoped in a type, so there is no outsider: the contract coverage lists
# this view in EXEMPT with the tests that call it.
class BoxTypeViewSet(ScopedReadOnlyViewSet):
    action_perms = {"list": AUTHENTICATED, "retrieve": AUTHENTICATED}
    serializer_class = BoxTypeOutputSerializer

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.box_type_list()

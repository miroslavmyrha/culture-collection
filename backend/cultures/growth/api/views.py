from functools import cached_property
from typing import Any

from django.db.models import Model, QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from cultures.core.api import ScopedReadOnlyViewSet
from cultures.core.errors import PROBLEM_CONTENT_TYPE as PROBLEM
from cultures.core.errors import ProblemSerializer
from cultures.growth import selectors, services
from cultures.growth.models import GrowthMedium
from cultures.labs import selectors as labs
from cultures.labs.access import access_of
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm

from .serializers import (
    MediumInputSerializer,
    MediumOutputSerializer,
    MediumRetireInputSerializer,
)

INVALID = OpenApiResponse(ProblemSerializer, "Invalid input, named by its field")
RETIRED = OpenApiResponse(ProblemSerializer, "medium_retired: a retired medium changes no more")
RULE = OpenApiResponse(ProblemSerializer, "reason_required")
LAB_PARAMETER = OpenApiParameter("lab_public_id", OpenApiTypes.UUID, OpenApiParameter.PATH)


# The lab's list of growth media, nested under the lab. The lab comes from the URL and is
# resolved through the caller's labs first: not a member gives 404 for every action. Every
# member who views strains reads the list; curators and managers write it (growth.manage_media),
# and the services re-read the role under the lab lock. A medium is retired, never deleted.
# (Comments, not docstrings: a docstring becomes the description of every operation.)
@extend_schema(parameters=[LAB_PARAMETER])
class MediumViewSet(ScopedReadOnlyViewSet):
    action_perms = {
        "list": Perm.VIEW_STRAINS,
        "retrieve": Perm.VIEW_STRAINS,
        "create": Perm.MANAGE_MEDIA,
        "update": Perm.MANAGE_MEDIA,
        "retire": Perm.MANAGE_MEDIA,
    }
    serializer_class = MediumOutputSerializer

    @cached_property
    def lab(self) -> Lab:
        return labs.lab_get(access=access_of(self.request), public_id=self.kwargs["lab_public_id"])

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        lab_id = obj.lab_id if isinstance(obj, GrowthMedium) else self.lab.pk
        return access_of(self.request).can(Perm(perm), lab_id)

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.medium_list(access=access_of(self.request), lab=self.lab)

    def _detail(self, medium: GrowthMedium) -> Response:
        fresh = self.scoped_queryset().get(pk=medium.pk)
        return Response(MediumOutputSerializer(fresh).data)

    @extend_schema(
        request=MediumInputSerializer,
        responses={201: MediumOutputSerializer, (400, PROBLEM): INVALID},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab  # first: an outsider gets 404, never a 400 that reveals the lab
        data = MediumInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        medium = services.medium_create(
            access=access_of(request),
            lab=lab,
            name=data.validated_data["name"],
            composition_reference=data.validated_data["composition_reference"],
        )
        response = self._detail(medium)
        response.status_code = status.HTTP_201_CREATED
        return response

    @extend_schema(
        request=MediumInputSerializer,
        responses={200: MediumOutputSerializer, (400, PROBLEM): INVALID, (409, PROBLEM): RETIRED},
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        medium: GrowthMedium = self.get_object()  # first: 404 or 403 before the input is read
        data = MediumInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.medium_update(
            access=access_of(request),
            medium=medium,
            name=data.validated_data["name"],
            composition_reference=data.validated_data["composition_reference"],
        )
        return self._detail(medium)

    @extend_schema(
        request=MediumRetireInputSerializer,
        responses={200: MediumOutputSerializer, (400, PROBLEM): INVALID, (422, PROBLEM): RULE},
    )
    @action(detail=True, methods=["post"], url_path="retire")
    def retire(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        medium: GrowthMedium = self.get_object()
        data = MediumRetireInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.medium_retire(
            access=access_of(request), medium=medium, reason=data.validated_data["reason"]
        )
        return self._detail(medium)

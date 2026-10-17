from functools import cached_property
from typing import Any

from django.db.models import Model, QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from cultures.core.api import ScopedModelViewSet, ScopedReadOnlyViewSet
from cultures.core.errors import PROBLEM_CONTENT_TYPE as PROBLEM
from cultures.core.errors import ProblemSerializer
from cultures.labs import selectors, services
from cultures.labs.access import access_of
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Perm

from .serializers import (
    LabOutputSerializer,
    MemberCreateInputSerializer,
    MemberOutputSerializer,
    MemberRoleInputSerializer,
)

# 401, 403, 404 and 429 with the Problem body are added to every operation by core.schema.
INVALID_MEMBER = OpenApiResponse(
    ProblemSerializer, "Invalid input, an unknown or inactive user, or already a member"
)
INVALID_ROLE = OpenApiResponse(ProblemSerializer, "Invalid role")
LAST_MANAGER = OpenApiResponse(ProblemSerializer, "The lab would have no manager left")
LAB_PARAMETER = OpenApiParameter("lab_public_id", OpenApiTypes.UUID, OpenApiParameter.PATH)


# My labs and my role in each. Labs are created by staff in Django admin, so the API
# only reads them. Rows are scoped by the access object: a lab the caller is not a
# member of answers 404, the same as a lab that does not exist.
# (Comments, not a docstring: a docstring becomes the description of every operation.)
class LabViewSet(ScopedReadOnlyViewSet):
    action_perms = {"list": Perm.VIEW_LAB, "retrieve": Perm.VIEW_LAB}
    serializer_class = LabOutputSerializer

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.lab_list(access=access_of(self.request))

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        if obj is None:
            return True  # the list: its rows are already the labs with the permission
        return access_of(self.request).can(Perm(perm), obj.pk)


# The members of one lab, nested under it. The lab comes from the URL and is resolved
# through the caller's labs first: not a member gives 404 for every action, before any
# role check or input validation. Then the role in that lab decides (403), and the
# services re-check the grant rules under the lab lock.
@extend_schema(parameters=[LAB_PARAMETER])
class MemberViewSet(ScopedModelViewSet):
    action_perms = {
        "list": Perm.VIEW_MEMBERS,
        "retrieve": Perm.VIEW_MEMBERS,
        "create": Perm.MANAGE_MEMBERS,
        "update": Perm.MANAGE_MEMBERS,
        "partial_update": Perm.MANAGE_MEMBERS,
        "destroy": Perm.MANAGE_MEMBERS,
    }
    serializer_class = MemberOutputSerializer

    @cached_property
    def lab(self) -> Lab:
        return selectors.lab_get(
            access=access_of(self.request), public_id=self.kwargs["lab_public_id"]
        )

    def scoped_queryset(self) -> QuerySet[Any]:
        # Only this lab's members: a membership of another lab is not found here, even
        # for a manager of both labs.
        return selectors.member_list(access=access_of(self.request), lab=self.lab)

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        lab_id = obj.lab_id if isinstance(obj, Membership) else self.lab.pk
        return access_of(self.request).can(Perm(perm), lab_id)

    @extend_schema(
        request=MemberCreateInputSerializer,
        responses={201: MemberOutputSerializer, (400, PROBLEM): INVALID_MEMBER},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = MemberCreateInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        membership = services.member_add(
            access=access_of(request),
            lab=self.lab,
            user=data.validated_data["username"],
            role=data.validated_data["role"],
        )
        return Response(MemberOutputSerializer(membership).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=MemberRoleInputSerializer,
        responses={
            200: MemberOutputSerializer,
            (400, PROBLEM): INVALID_ROLE,
            (422, PROBLEM): LAST_MANAGER,
        },
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        membership: Membership = self.get_object()  # first: an outsider gets 404, never a 400
        data = MemberRoleInputSerializer(data=request.data, partial=kwargs.get("partial", False))
        data.is_valid(raise_exception=True)
        if "role" in data.validated_data:
            membership = services.member_change_role(
                access=access_of(request), membership=membership, role=data.validated_data["role"]
            )
        return Response(MemberOutputSerializer(membership).data)

    @extend_schema(
        request=MemberRoleInputSerializer,
        responses={
            200: MemberOutputSerializer,
            (400, PROBLEM): INVALID_ROLE,
            (422, PROBLEM): LAST_MANAGER,
        },
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.update(request, *args, partial=True, **kwargs)

    @extend_schema(responses={204: None, (422, PROBLEM): LAST_MANAGER})
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.member_remove(access=access_of(request), membership=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

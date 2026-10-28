from functools import cached_property
from typing import Any

from django.db.models import Model, QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from cultures.core.api import ScopedModelViewSet, ScopedReadOnlyViewSet
from cultures.core.errors import PROBLEM_CONTENT_TYPE as PROBLEM
from cultures.core.errors import ProblemSerializer
from cultures.labs import selectors, services
from cultures.labs.access import access_of
from cultures.labs.models import Lab, LocationGrant, Membership
from cultures.labs.permissions import Perm
from cultures.lineage import selectors as lineage
from cultures.lineage.api.serializers import RevealFilterSerializer, RevealLogEntrySerializer

from .serializers import (
    LabOutputSerializer,
    LocationGrantInputSerializer,
    LocationGrantOutputSerializer,
    LocationRevokeInputSerializer,
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
PAGE_PARAMETERS = [
    OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, description="At most 200"),
    OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY),
]


# My labs and my role in each. Labs are created by staff in Django admin, so the API
# only reads them. Rows are scoped by the access object: a lab the caller is not a
# member of answers 404, the same as a lab that does not exist.
# (Comments, not a docstring: a docstring becomes the description of every operation.)
class LabViewSet(ScopedReadOnlyViewSet):
    action_perms = {
        "list": Perm.VIEW_LAB,
        "retrieve": Perm.VIEW_LAB,
        "reveals": Perm.VIEW_REVEALS,
    }
    serializer_class = LabOutputSerializer

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.lab_list(access=access_of(self.request))

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        if obj is None:
            return True  # the list: its rows are already the labs with the permission
        return access_of(self.request).can(Perm(perm), obj.pk)

    @extend_schema(
        parameters=[RevealFilterSerializer, *PAGE_PARAMETERS],
        responses={200: RevealLogEntrySerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="reveals")
    def reveals(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Who revealed where the lab's regulated vials are (#83, ADR 0009), newest first, a page
        at a time: the person, the vial and its strain, and when. Never the place: the events
        hold none. For the lab's managers; a member of another role gets 403."""
        lab: Lab = self.get_object()  # first: an outsider gets 404, another role 403
        query = RevealFilterSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = lineage.reveal_list(access=access_of(request), lab=lab, **query.validated_data)
        page = self.paginate_queryset(rows) or []
        return self.get_paginated_response([RevealLogEntrySerializer(r).data for r in page])


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


GRANT_INVALID = OpenApiResponse(
    ProblemSerializer, "An unknown member, or one who holds the grant already (already_granted)"
)
REASON = OpenApiResponse(ProblemSerializer, "reason_required")
REVOKED = OpenApiResponse(ProblemSerializer, "grant_revoked: revoked already")


# Who may see where the lab's regulated strains are stored (ADR 0009, amendment of
# 2026-10-19). Part of no role: a manager grants it to a member and revokes it, each with a
# reason. Only managers list the grants (labs.manage_members): the list of people who may
# find regulated agents is itself kept to few. The list holds the open grants, not paged.
@extend_schema(parameters=[LAB_PARAMETER])
class LocationGrantViewSet(ScopedReadOnlyViewSet):
    action_perms = {
        "list": Perm.MANAGE_MEMBERS,
        "retrieve": Perm.MANAGE_MEMBERS,
        "create": Perm.MANAGE_MEMBERS,
        "revoke": Perm.MANAGE_MEMBERS,
    }
    serializer_class = LocationGrantOutputSerializer
    pagination_class = None

    @cached_property
    def lab(self) -> Lab:
        return selectors.lab_get(
            access=access_of(self.request), public_id=self.kwargs["lab_public_id"]
        )

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.location_grant_list(access=access_of(self.request), lab=self.lab)

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        lab_id = obj.lab_id if isinstance(obj, LocationGrant) else self.lab.pk
        return access_of(self.request).can(Perm(perm), lab_id)

    @extend_schema(
        request=LocationGrantInputSerializer,
        responses={
            201: LocationGrantOutputSerializer,
            (400, PROBLEM): GRANT_INVALID,
            (422, PROBLEM): REASON,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab  # first: an outsider gets 404, never a 400 that reveals the lab
        data = LocationGrantInputSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        data.is_valid(raise_exception=True)
        membership: Membership = data.validated_data["member"]
        if membership.lab_id != lab.pk:  # the same error as an unknown member
            raise services.UnknownMember
        grant = services.location_grant_add(
            access=access_of(request),
            lab=lab,
            membership=membership,
            reason=data.validated_data["reason"],
        )
        fresh = self.scoped_queryset().get(pk=grant.pk)
        return Response(LocationGrantOutputSerializer(fresh).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=LocationRevokeInputSerializer,
        responses={204: None, (409, PROBLEM): REVOKED, (422, PROBLEM): REASON},
    )
    @action(detail=True, methods=["post"], url_path="revoke")
    def revoke(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        grant: LocationGrant = self.get_object()
        data = LocationRevokeInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.location_grant_revoke(
            access=access_of(request), grant=grant, reason=data.validated_data["reason"]
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

from functools import cached_property
from typing import Any

from django.db.models import Model, QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from cultures.biosafety.models import RestrictionKind
from cultures.core.api import ScopedReadOnlyViewSet
from cultures.core.errors import PROBLEM_CONTENT_TYPE as PROBLEM
from cultures.core.errors import ProblemSerializer
from cultures.core.exceptions import NotFound
from cultures.deposits import selectors as deposits
from cultures.deposits.api.serializers import StrainTermsOutputSerializer
from cultures.labs import selectors as labs
from cultures.labs.access import access_of
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.overview import activity
from cultures.overview.api.serializers import HistoryLineSerializer, HistoryPageSerializer
from cultures.strains import selectors, services
from cultures.strains.filters import StrainFilter
from cultures.strains.models import Strain, StrainRestriction

from .serializers import (
    ReclassifyInputSerializer,
    RestrictionAddInputSerializer,
    RestrictionEndInputSerializer,
    RiskGroupInputSerializer,
    StrainDetailOutputSerializer,
    StrainListOutputSerializer,
)

# 401, 403, 404 and 429 with the Problem body are added to every operation by core.schema.
INVALID = OpenApiResponse(
    ProblemSerializer,
    "Invalid input, an unknown taxon, a risk group 4 agent, or a group above the cap of a box"
    " holding the strain's vials (risk_group_above_box_cap), on risk_group",
)
RULE = OpenApiResponse(
    ProblemSerializer,
    "lab_authorisation_required: the lab holds no valid permit for a restriction's kind;"
    " reason_required",
)
ENDED = OpenApiResponse(ProblemSerializer, "The restriction has ended already")
LAB_PARAMETER = OpenApiParameter("lab_public_id", OpenApiTypes.UUID, OpenApiParameter.PATH)
RESTRICTION_PARAMETER = OpenApiParameter("restriction_id", OpenApiTypes.UUID, OpenApiParameter.PATH)
PAGE_PARAMETERS = [
    OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, description="At most 200"),
    OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY),
]


def restrictions_of(items: list[dict[str, Any]]) -> list[services.RestrictionInput]:
    return [
        services.RestrictionInput(
            kind=RestrictionKind(item["kind"]),
            reference=item["reference"],
            act=item["act"],
            gmo_category=item["gmo_category"],
        )
        for item in items
    ]


# The strains of one lab, nested under it. The lab comes from the URL and is resolved
# through the caller's labs first: not a member gives 404 for every action, before any
# role check or input validation. Viewers and up read (strains.view), curators and up
# write (strains.manage); the services re-read the role under the lab lock. Strains are
# never changed in place or deleted: each change is an action with its reason. They are not
# created here either: a strain comes from an accepted deposit (deposits, ADR 0008 amendment
# of 2026-10-19), and later from the catalogue import.
# (Comments, not a docstring: a docstring becomes the description of every operation.)
@extend_schema(parameters=[LAB_PARAMETER])
class StrainViewSet(ScopedReadOnlyViewSet):
    action_perms = {
        "list": Perm.VIEW_STRAINS,
        "retrieve": Perm.VIEW_STRAINS,
        "reclassify": Perm.MANAGE_STRAINS,
        "risk_group": Perm.MANAGE_STRAINS,
        "add_restriction": Perm.MANAGE_STRAINS,
        "end_restriction": Perm.MANAGE_STRAINS,
        "history": Perm.VIEW_STRAINS,
        "terms": Perm.VIEW_TERMS,
    }
    filterset_class = StrainFilter

    @cached_property
    def lab(self) -> Lab:
        return labs.lab_get(access=access_of(self.request), public_id=self.kwargs["lab_public_id"])

    def get_serializer_class(self) -> type[StrainListOutputSerializer]:
        return StrainListOutputSerializer if self.action == "list" else StrainDetailOutputSerializer

    def scoped_queryset(self) -> QuerySet[Any]:
        access = access_of(self.request)
        if self.action == "list":
            return selectors.strain_list(access=access, lab=self.lab)
        if self.action in ("history", "terms"):
            return selectors.strain_rows(access=access, lab=self.lab)
        return selectors.strain_detail(access=access, lab=self.lab)

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        lab_id = obj.lab_id if isinstance(obj, Strain) else self.lab.pk
        return access_of(self.request).can(Perm(perm), lab_id)

    def _detail(self, strain: Strain) -> Response:
        fresh = selectors.strain_detail(access=access_of(self.request), lab=self.lab).get(
            pk=strain.pk
        )
        return Response(StrainDetailOutputSerializer(fresh).data)

    @extend_schema(
        request=ReclassifyInputSerializer,
        responses={
            200: StrainDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="reclassify")
    def reclassify(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        strain: Strain = self.get_object()  # first: 404 or 403 before the input is read
        data = ReclassifyInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        services.strain_reclassify(
            access=access_of(request),
            strain=strain,
            taxon=values["taxon"],
            identified_on=values["identified_on"],
            method=values["method"],
            reason=values["reason"],
        )
        return self._detail(strain)

    @extend_schema(
        request=RiskGroupInputSerializer,
        responses={
            200: StrainDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="risk-group")
    def risk_group(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        strain: Strain = self.get_object()
        data = RiskGroupInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.strain_set_risk_group(
            access=access_of(request),
            strain=strain,
            risk_group=data.validated_data["risk_group"],
            reason=data.validated_data["reason"],
        )
        return self._detail(strain)

    @extend_schema(
        request=RestrictionAddInputSerializer,
        responses={
            200: StrainDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="restrictions")
    def add_restriction(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        strain: Strain = self.get_object()
        data = RestrictionAddInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        (restriction,) = restrictions_of([values])
        services.strain_restriction_add(
            access=access_of(request),
            strain=strain,
            restriction=restriction,
            reason=values["reason"],
        )
        return self._detail(strain)

    @extend_schema(
        parameters=[RESTRICTION_PARAMETER],
        request=RestrictionEndInputSerializer,
        responses={200: StrainDetailOutputSerializer, (409, PROBLEM): ENDED, (422, PROBLEM): RULE},
    )
    @action(
        detail=True, methods=["post"], url_path=r"restrictions/(?P<restriction_id>[0-9a-f-]+)/end"
    )
    def end_restriction(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        strain: Strain = self.get_object()
        # Through the strain: a restriction of another strain is not found here.
        history: list[StrainRestriction] = vars(strain)["all_restrictions"]  # the prefetch
        restriction = next(
            (r for r in history if str(r.public_id) == kwargs["restriction_id"]), None
        )
        if restriction is None:
            raise NotFound
        data = RestrictionEndInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.strain_restriction_end(
            access=access_of(request), restriction=restriction, reason=data.validated_data["reason"]
        )
        return self._detail(strain)

    @extend_schema(parameters=PAGE_PARAMETERS, responses={200: HistoryPageSerializer})
    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Everything that happened to the strain that the person may read, newest first, one
        line each, a page at a time: the rules of the activity on Home (overview.activity). A
        line names its subject and the actor's pseudonymous label, never a location or a
        person's data."""
        strain: Strain = self.get_object()
        access = access_of(request)
        page = self.paginate_queryset(activity.strain_history(access=access, strain=strain))
        rows = activity.lines(page or [], access=access)
        return self.get_paginated_response([HistoryLineSerializer(row).data for row in rows])

    @extend_schema(responses={200: StrainTermsOutputSerializer})
    @action(detail=True, methods=["get"], url_path="terms")
    def terms(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The strain's terms of use, every version newest first, with the MTA each names. The
        deposit they belong to only for a reader who may open deposits."""
        strain: Strain = self.get_object()
        access = access_of(request)
        versions = list(deposits.strain_terms(access=access, strain=strain))
        deposit = versions[0].deposit.public_id if versions else None
        shown = deposit if access.can(Perm.VIEW_DEPOSITS, strain.lab_id) else None
        data = {"deposit": shown, "versions": versions}
        return Response(StrainTermsOutputSerializer(data).data)

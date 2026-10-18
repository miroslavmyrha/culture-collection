from functools import cached_property
from typing import Any

from django.db.models import Model, QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from cultures.biosafety.models import RestrictionKind
from cultures.core.api import ScopedReadOnlyViewSet
from cultures.core.errors import PROBLEM_CONTENT_TYPE as PROBLEM
from cultures.core.errors import ProblemSerializer
from cultures.core.exceptions import NotFound
from cultures.labs import selectors as labs
from cultures.labs.access import access_of
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.strains import selectors, services
from cultures.strains.filters import StrainFilter
from cultures.strains.models import Pathogenicity, Strain, StrainRestriction

from .serializers import (
    ReclassifyInputSerializer,
    RestrictionAddInputSerializer,
    RestrictionEndInputSerializer,
    RiskGroupInputSerializer,
    StrainCreateInputSerializer,
    StrainDetailOutputSerializer,
    StrainListOutputSerializer,
)

# 401, 403, 404 and 429 with the Problem body are added to every operation by core.schema.
INVALID = OpenApiResponse(
    ProblemSerializer, "Invalid input, an unknown taxon, or a risk group 4 agent (on risk_group)"
)
TAKEN = OpenApiResponse(ProblemSerializer, "The accession number is taken: try again")
RULE = OpenApiResponse(
    ProblemSerializer,
    "lab_authorisation_required: the lab holds no valid permit for a restriction's kind;"
    " reason_required",
)
ENDED = OpenApiResponse(ProblemSerializer, "The restriction has ended already")
LAB_PARAMETER = OpenApiParameter("lab_public_id", OpenApiTypes.UUID, OpenApiParameter.PATH)
RESTRICTION_PARAMETER = OpenApiParameter("restriction_id", OpenApiTypes.UUID, OpenApiParameter.PATH)


def _restrictions(items: list[dict[str, Any]]) -> list[services.RestrictionInput]:
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
# never changed in place or deleted: each change is an action with its reason.
# (Comments, not a docstring: a docstring becomes the description of every operation.)
@extend_schema(parameters=[LAB_PARAMETER])
class StrainViewSet(ScopedReadOnlyViewSet):
    action_perms = {
        "list": Perm.VIEW_STRAINS,
        "retrieve": Perm.VIEW_STRAINS,
        "create": Perm.MANAGE_STRAINS,
        "reclassify": Perm.MANAGE_STRAINS,
        "risk_group": Perm.MANAGE_STRAINS,
        "add_restriction": Perm.MANAGE_STRAINS,
        "end_restriction": Perm.MANAGE_STRAINS,
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
        request=StrainCreateInputSerializer,
        responses={
            201: StrainDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): TAKEN,
            (422, PROBLEM): RULE,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab  # first: an outsider gets 404, never a 400 that reveals the lab
        data = StrainCreateInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        strain = services.strain_create(
            access=access_of(request),
            lab=lab,
            data=services.NewStrain(
                name_as_received=values["name_as_received"],
                taxon=values["taxon"],
                identified_on=values["identified_on"],
                identification_method=values["identification_method"],
                risk_group=values["risk_group"],
                animal_pathogenicity=Pathogenicity(values["animal_pathogenicity"]),
                plant_pathogenicity=Pathogenicity(values["plant_pathogenicity"]),
                isolation_source=values["isolation_source"],
                country_of_origin=values["country_of_origin"],
                isolation_date=values["isolation_date"],
                restrictions=_restrictions(values["restrictions"]),
            ),
        )
        response = self._detail(strain)
        response.status_code = status.HTTP_201_CREATED
        return response

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
        (restriction,) = _restrictions([values])
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

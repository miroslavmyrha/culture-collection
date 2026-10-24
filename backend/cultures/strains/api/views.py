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
    EndConfirmInputSerializer,
    EndProposeInputSerializer,
    EndWithdrawInputSerializer,
    ReclassifyInputSerializer,
    RestrictionAddInputSerializer,
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
PROPOSED = OpenApiResponse(
    ProblemSerializer,
    "restriction_ended; end_proposed: someone proposed to end it already, a proposal waits",
)
SETTLED = OpenApiResponse(
    ProblemSerializer,
    "restriction_ended; end_not_proposed: no proposal is open; end_proposal_changed: another"
    " proposal is open than the one named",
)
OWN = OpenApiResponse(
    ProblemSerializer,
    "permission_denied: confirming is a manager's; confirm_own_end_proposal: the caller proposed"
    " it, a different manager confirms",
)
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
        # #105: a restriction ends in two steps, by two people (ADR 0009).
        "propose_end": Perm.MANAGE_STRAINS,
        "confirm_end": Perm.CONFIRM_RESTRICTION_END,
        "withdraw_end": Perm.MANAGE_STRAINS,
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
        # The request in the context: a proposal says whether the caller may confirm it.
        return Response(
            StrainDetailOutputSerializer(fresh, context=self.get_serializer_context()).data
        )

    def _restriction(self, strain: Strain, restriction_id: str) -> StrainRestriction:
        # Through the strain: a restriction of another strain is not found here.
        history: list[StrainRestriction] = vars(strain)["all_restrictions"]  # the prefetch
        restriction = next((r for r in history if str(r.public_id) == restriction_id), None)
        if restriction is None:
            raise NotFound
        return restriction

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
        request=EndProposeInputSerializer,
        responses={
            200: StrainDetailOutputSerializer,
            (409, PROBLEM): PROPOSED,
            (422, PROBLEM): RULE,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"restrictions/(?P<restriction_id>[0-9a-f-]+)/end-proposal",
    )
    def propose_end(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Proposes to end a restriction, with the reason it will end with (#105). The
        restriction stays active until a manager other than the proposer confirms it."""
        strain: Strain = self.get_object()
        restriction = self._restriction(strain, kwargs["restriction_id"])
        data = EndProposeInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.strain_restriction_end_propose(
            access=access_of(request), restriction=restriction, reason=data.validated_data["reason"]
        )
        return self._detail(strain)

    @extend_schema(
        parameters=[RESTRICTION_PARAMETER],
        request=EndConfirmInputSerializer,
        responses={200: StrainDetailOutputSerializer, (403, PROBLEM): OWN, (409, PROBLEM): SETTLED},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"restrictions/(?P<restriction_id>[0-9a-f-]+)/end-proposal/confirm",
    )
    def confirm_end(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """A manager other than the proposer confirms the proposal they read: the restriction
        ends now, with the proposal's reason."""
        strain: Strain = self.get_object()
        restriction = self._restriction(strain, kwargs["restriction_id"])
        data = EndConfirmInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.strain_restriction_end_confirm(
            access=access_of(request),
            restriction=restriction,
            proposal=data.validated_data["proposal"],
        )
        return self._detail(strain)

    @extend_schema(
        parameters=[RESTRICTION_PARAMETER],
        request=EndWithdrawInputSerializer,
        responses={
            200: StrainDetailOutputSerializer,
            (409, PROBLEM): SETTLED,
            (422, PROBLEM): RULE,
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"restrictions/(?P<restriction_id>[0-9a-f-]+)/end-proposal/withdraw",
    )
    def withdraw_end(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Withdraws the open proposal the caller read, with a reason. The restriction stays."""
        strain: Strain = self.get_object()
        restriction = self._restriction(strain, kwargs["restriction_id"])
        data = EndWithdrawInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.strain_restriction_end_withdraw(
            access=access_of(request),
            restriction=restriction,
            proposal=data.validated_data["proposal"],
            reason=data.validated_data["reason"],
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

from collections.abc import Sequence
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
from cultures.growth.services import Growth
from cultures.labs import selectors as labs
from cultures.labs.access import access_of
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.labs.services import holds_location_grant
from cultures.lineage import selectors, services
from cultures.lineage.filters import BatchCheckFilter, BatchFilter, PassageFilter, VialFilter
from cultures.lineage.models import (
    Batch,
    BatchCheck,
    CheckKind,
    CheckMethod,
    CheckResult,
    CheckStage,
    CheckUnit,
    Method,
    Passage,
    Purpose,
    Vial,
    VialStatus,
)
from cultures.storage.models import StorageUnit

from .serializers import (
    BarcodeInputSerializer,
    BatchCheckOutputSerializer,
    BatchDecisionInputSerializer,
    BatchOutputSerializer,
    BoxGridOutputSerializer,
    BoxOutputSerializer,
    CheckErrorInputSerializer,
    CheckInputSerializer,
    GrowthOverrideInputSerializer,
    LocationSerializer,
    PassageOutputSerializer,
    PlaceInputSerializer,
    PreserveInputSerializer,
    RevealOutputSerializer,
    SubcultureInputSerializer,
    VialOutputSerializer,
    VialStatusInputSerializer,
)

# 401, 403, 404 and 429 with the Problem body are added to every operation by core.schema.
INVALID = OpenApiResponse(
    ProblemSerializer,
    "Invalid input on a field: an unknown passage or box, a box that may not take the strain"
    " (not_a_box, unit_not_active, risk_group_above_cap), a full box (box_full), a position"
    " outside the box (outside_box), a date in the future, a state that cannot follow",
)
CONFLICT = OpenApiResponse(
    ProblemSerializer,
    "strain_not_active; position_taken; vial_not_in_collection; batch_number_taken",
)
RULE = OpenApiResponse(ProblemSerializer, "reason_required")
RELEASE_RULE = OpenApiResponse(
    ProblemSerializer,
    "reason_required; checks_not_passed: the latest identity, purity or viability check is"
    " missing or failed",
)
DECISION_CONFLICT = OpenApiResponse(ProblemSerializer, "batch_exhausted")
CHECK_INVALID = OpenApiResponse(
    ProblemSerializer,
    "Invalid input on a field: an unknown batch, vial or check to correct, a method that is not"
    " of the kind, a value without its unit, a reduced result without a note, a date in the"
    " future or before the batch was preserved",
)
CHECK_CONFLICT = OpenApiResponse(
    ProblemSerializer,
    "batch_exhausted; vial_not_available; check_entered_in_error; vial_not_in_collection",
)
LAB_PARAMETER = OpenApiParameter("lab_public_id", OpenApiTypes.UUID, OpenApiParameter.PATH)


def growth_of(values: dict[str, Any] | None) -> Growth | None:
    """The conditions the caller gave, or None: the passage then records the strain's."""
    if values is None:
        return None
    return Growth(
        medium=values["medium"],
        temperature_low_c=values["temperature_low_c"],
        temperature_high_c=values["temperature_high_c"],
        atmosphere=values["atmosphere"],
    )


class LabNested(ScopedReadOnlyViewSet, abstract=True):
    """The lab comes from the URL and is resolved through the caller's labs first: not a
    member gives 404 for every action, before any role check or input validation."""

    model: type[Model]

    @cached_property
    def lab(self) -> Lab:
        return labs.lab_get(access=access_of(self.request), public_id=self.kwargs["lab_public_id"])

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        lab_id = obj.lab_id if isinstance(obj, self.model) else self.lab.pk  # type: ignore[attr-defined]
        return access_of(self.request).can(Perm(perm), lab_id)


# Passages of the lab's strains: the material as received (from the deposit), subcultures and
# revivals. Viewers and up read (strains.view); technicians and up grow a subculture
# (vials.handle). A revival is an action of the vial it consumes. Passages are never changed
# or deleted. (Comments, not a docstring: a docstring becomes the description of every
# operation.)
@extend_schema(parameters=[LAB_PARAMETER])
class PassageViewSet(LabNested):
    model = Passage
    action_perms = {
        "list": Perm.VIEW_STRAINS,
        "retrieve": Perm.VIEW_STRAINS,
        "create": Perm.HANDLE_VIALS,
    }
    serializer_class = PassageOutputSerializer
    filterset_class = PassageFilter

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.passage_list(access=access_of(self.request), lab=self.lab)

    @extend_schema(
        request=SubcultureInputSerializer,
        responses={
            201: PassageOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): CONFLICT,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab  # first: an outsider gets 404, never a 400 that reveals the lab
        data = SubcultureInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        parent: Passage = data.validated_data["source_passage"]
        if parent.lab_id != lab.pk:  # the same error as an unknown passage
            raise services.InvalidVial(
                "Invalid passage.", code="does_not_exist", attr="source_passage"
            )
        passage = services.passage_subculture(
            access=access_of(request),
            parent=parent,
            growth=growth_of(data.validated_data["growth"]),
        )
        fresh = self.scoped_queryset().get(pk=passage.pk)
        return Response(PassageOutputSerializer(fresh).data, status=status.HTTP_201_CREATED)


# Batches of the lab's strains: one preservation of one passage each. Viewers and up read
# (strains.view); technicians and up preserve (vials.handle), optionally into a box in fill
# order. Curators and up release a batch once its latest identity, purity and viability checks
# passed, or hold it, each with a reason (batches.release). A failed check holds it on its own.
# A batch is never deleted.
@extend_schema(parameters=[LAB_PARAMETER])
class BatchViewSet(LabNested):
    model = Batch
    action_perms = {
        "list": Perm.VIEW_STRAINS,
        "retrieve": Perm.VIEW_STRAINS,
        "create": Perm.HANDLE_VIALS,
        "release": Perm.RELEASE_BATCHES,
        "hold": Perm.RELEASE_BATCHES,
    }
    serializer_class = BatchOutputSerializer
    filterset_class = BatchFilter

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.batch_list(access=access_of(self.request), lab=self.lab)

    @extend_schema(
        request=PreserveInputSerializer,
        responses={
            201: BatchOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): CONFLICT,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab
        data = PreserveInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        passage: Passage = values["passage"]
        if passage.lab_id != lab.pk:
            raise services.InvalidVial("Invalid passage.", code="does_not_exist", attr="passage")
        batch = services.batch_preserve(
            access=access_of(request),
            passage=passage,
            data=services.NewBatch(
                method=Method(values["method"]),
                purpose=Purpose(values["purpose"]),
                preserved_on=values["preserved_on"],
                vial_count=values["vial_count"],
                cryoprotectant=values["cryoprotectant"],
                box=values["box"],
            ),
        )
        fresh = self.scoped_queryset().get(pk=batch.pk)
        return Response(BatchOutputSerializer(fresh).data, status=status.HTTP_201_CREATED)

    def _decided(self, batch: Batch) -> Response:
        """The batch as committed now, with its checks, through the same scoped query."""
        return Response(BatchOutputSerializer(self.scoped_queryset().get(pk=batch.pk)).data)

    @extend_schema(
        request=BatchDecisionInputSerializer,
        responses={
            200: BatchOutputSerializer,
            (409, PROBLEM): DECISION_CONFLICT,
            (422, PROBLEM): RELEASE_RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="release")
    def release(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        batch: Batch = self.get_object()  # first: 404 or 403 before the input is read
        data = BatchDecisionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.batch_release(
            access=access_of(request), batch=batch, reason=data.validated_data["reason"]
        )
        return self._decided(batch)

    @extend_schema(
        request=BatchDecisionInputSerializer,
        responses={
            200: BatchOutputSerializer,
            (409, PROBLEM): DECISION_CONFLICT,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="hold")
    def hold(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        batch: Batch = self.get_object()
        data = BatchDecisionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.batch_hold(
            access=access_of(request), batch=batch, reason=data.validated_data["reason"]
        )
        return self._decided(batch)


# The checks of the lab's batches (#17, ADR 0008, D16): identity, purity and viability, newest
# first, entered in error included. Viewers and up read (strains.view); technicians and up
# record a check, which may consume the vial checked and move the batch, and enter a wrong one
# in error with a reason (vials.handle). A check is never changed otherwise or deleted.
@extend_schema(parameters=[LAB_PARAMETER])
class BatchCheckViewSet(LabNested):
    model = BatchCheck
    action_perms = {
        "list": Perm.VIEW_STRAINS,
        "retrieve": Perm.VIEW_STRAINS,
        "create": Perm.HANDLE_VIALS,
        "enter_in_error": Perm.HANDLE_VIALS,
    }
    serializer_class = BatchCheckOutputSerializer
    filterset_class = BatchCheckFilter

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.check_list(access=access_of(self.request), lab=self.lab)

    @extend_schema(
        request=CheckInputSerializer,
        responses={
            201: BatchCheckOutputSerializer,
            (400, PROBLEM): CHECK_INVALID,
            (409, PROBLEM): CHECK_CONFLICT,
            (422, PROBLEM): RULE,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab  # first: an outsider gets 404, never a 400 that reveals the lab
        data = CheckInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        batch: Batch = values["batch"]
        if batch.lab_id != lab.pk:  # the same error as an unknown batch
            raise services.InvalidCheck("Invalid batch.", code="does_not_exist", attr="batch")
        unit = values["unit"]
        check = services.check_record(
            access=access_of(request),
            batch=batch,
            data=services.NewCheck(
                kind=CheckKind(values["kind"]),
                stage=CheckStage(values["stage"]),
                checked_on=values["checked_on"],
                method=CheckMethod(values["method"]),
                result=CheckResult(values["result"]),
                method_detail=values["method_detail"],
                value=values["value"],
                unit=None if unit is None else CheckUnit(unit),
                vial=values["vial"],
                note=values["note"],
            ),
            supersedes=values["supersedes"],
            reason=values["reason"],
        )
        fresh = self.scoped_queryset().get(pk=check.pk)
        return Response(BatchCheckOutputSerializer(fresh).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=CheckErrorInputSerializer,
        responses={
            200: BatchCheckOutputSerializer,
            (409, PROBLEM): CHECK_CONFLICT,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="enter-in-error")
    def enter_in_error(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        check: BatchCheck = self.get_object()
        data = CheckErrorInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.check_enter_in_error(
            access=access_of(request), check=check, reason=data.validated_data["reason"]
        )
        return Response(BatchCheckOutputSerializer(self.scoped_queryset().get(pk=check.pk)).data)


# Vials of the lab's strains, paged, by strain, batch and number. Viewers and up read
# (strains.view); technicians and up place, move, change the state, set a barcode and revive
# (vials.handle). The location of a vial of a regulated strain is never in this list or in
# any answer but the reveal, which needs the lab's location grant (ADR 0009, amendment of
# 2026-10-19). Vials are never deleted.
@extend_schema(parameters=[LAB_PARAMETER])
class VialViewSet(LabNested):
    model = Vial
    action_perms = {
        "list": Perm.VIEW_STRAINS,
        "retrieve": Perm.VIEW_STRAINS,
        "place": Perm.HANDLE_VIALS,
        "set_status": Perm.HANDLE_VIALS,
        "barcode": Perm.HANDLE_VIALS,
        "revive": Perm.HANDLE_VIALS,
        "reveal_location": Perm.VIEW_STRAINS,
    }
    serializer_class = VialOutputSerializer
    filterset_class = VialFilter

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.vial_list(access=access_of(self.request), lab=self.lab)

    def _context(self, vials: Sequence[Vial]) -> dict[str, Any]:
        """The box paths of the rows shown, in one query, and whether the reader may reveal."""
        boxes = [p.box for vial in vials for p in vars(vial)["open_placements"]]
        return {
            **self.get_serializer_context(),
            "paths": selectors.box_paths(boxes),
            "may_reveal": holds_location_grant(
                lab_id=self.lab.pk, user=access_of(self.request).user
            ),
        }

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = list(page if page is not None else queryset)
        data = VialOutputSerializer(rows, many=True, context=self._context(rows)).data
        return self.get_paginated_response(data) if page is not None else Response(data)

    def _shown(self, vial: Vial) -> Response:
        return Response(VialOutputSerializer(vial, context=self._context([vial])).data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._shown(self.get_object())

    def _detail(self, vial: Vial) -> Response:
        """The vial as committed now, through the same scoped query: masked when regulated."""
        return self._shown(self.scoped_queryset().get(pk=vial.pk))

    @extend_schema(
        request=PlaceInputSerializer,
        responses={
            200: VialOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): CONFLICT,
        },
    )
    @action(detail=True, methods=["post"], url_path="place")
    def place(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        vial: Vial = self.get_object()  # first: 404 or 403 before the input is read
        data = PlaceInputSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        values = data.validated_data
        services.vial_place(
            access=access_of(request),
            vial=vial,
            box=values["box"],
            row=values["row"],
            col=values["col"],
        )
        return self._detail(vial)

    @extend_schema(
        request=VialStatusInputSerializer,
        responses={
            200: VialOutputSerializer,
            (400, PROBLEM): INVALID,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        vial: Vial = self.get_object()
        data = VialStatusInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.vial_transition(
            access=access_of(request),
            vial=vial,
            status=VialStatus(data.validated_data["status"]),
            reason=data.validated_data["reason"],
        )
        return self._detail(vial)

    @extend_schema(
        request=BarcodeInputSerializer,
        responses={200: VialOutputSerializer, (400, PROBLEM): INVALID},
    )
    @action(detail=True, methods=["post"], url_path="barcode")
    def barcode(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        vial: Vial = self.get_object()
        data = BarcodeInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.vial_set_barcode(
            access=access_of(request), vial=vial, barcode=data.validated_data["barcode"]
        )
        return self._detail(vial)

    @extend_schema(
        request=GrowthOverrideInputSerializer,
        responses={
            201: PassageOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): CONFLICT,
        },
    )
    @action(detail=True, methods=["post"], url_path="revive")
    def revive(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        vial: Vial = self.get_object()
        data = GrowthOverrideInputSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        data.is_valid(raise_exception=True)
        passage = services.vial_revive(
            access=access_of(request), vial=vial, growth=growth_of(data.validated_data["growth"])
        )
        fresh = selectors.passage_list(access=access_of(request), lab=self.lab).get(pk=passage.pk)
        return Response(PassageOutputSerializer(fresh).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses={
            200: RevealOutputSerializer,
            (403, PROBLEM): OpenApiResponse(
                ProblemSerializer, "location_grant_required: the caller holds no location grant"
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="reveal-location")
    def reveal_location(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        vial: Vial = self.get_object()
        location = services.vial_reveal_location(access=access_of(request), vial=vial)
        body = {"location": None if location is None else LocationSerializer(location).data}
        response = Response(body)  # the shape of RevealOutputSerializer
        response["Cache-Control"] = "no-store"  # shown once, kept by no cache
        return response


# The boxes of the lab with what their positions hold: the box grid (#15). Viewers and up read
# (strains.view, on boxes they see through storage.view; both are a viewer's). A taken position
# of a regulated strain's vial is `masked` and names no vial, to every reader (ADR 0009).
# Vials are placed and moved through the vial's place action. The list is paged, by tree order;
# a box's positions come in one query, never one per position.
@extend_schema(parameters=[LAB_PARAMETER])
class BoxViewSet(LabNested):
    model = StorageUnit
    action_perms = {
        "list": Perm.VIEW_STRAINS,
        "retrieve": Perm.VIEW_STRAINS,
    }

    def get_serializer_class(self) -> type[BoxOutputSerializer]:
        return BoxOutputSerializer if self.action == "list" else BoxGridOutputSerializer

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.box_list(access=access_of(self.request), lab=self.lab)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        box: StorageUnit = self.get_object()
        positions = selectors.box_positions(access=access_of(request), box=box)
        return Response(BoxGridOutputSerializer(box, context={"positions": positions}).data)

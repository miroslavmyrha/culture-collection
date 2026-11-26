from functools import cached_property
from typing import Any

from django.db.models import Model, QuerySet
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer

from cultures.biosafety.models import RestrictionKind
from cultures.core.api import ScopedReadOnlyViewSet
from cultures.core.errors import PROBLEM_CONTENT_TYPE as PROBLEM
from cultures.core.errors import ProblemSerializer
from cultures.core.parsers import LimitedJSONParser
from cultures.deposits import catalogue, selectors, services
from cultures.deposits.filters import DepositFilter, DepositorFilter
from cultures.deposits.models import AbsScope, Condition, Decision, Deposit, Depositor, Use
from cultures.labs import selectors as labs
from cultures.labs.access import access_of
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.strains import services as strains
from cultures.strains.api.serializers import StrainFactsInputSerializer
from cultures.strains.models import Pathogenicity

from .serializers import (
    CatalogueCheckInputSerializer,
    CatalogueCheckOutputSerializer,
    CatalogueImportInputSerializer,
    CatalogueImportOutputSerializer,
    DepositDetailOutputSerializer,
    DepositListOutputSerializer,
    DepositorInputSerializer,
    DepositorOutputSerializer,
    DepositReceiveInputSerializer,
    MtaTemplateDetailOutputSerializer,
    MtaTemplateInputSerializer,
    MtaTemplateListOutputSerializer,
    RejectInputSerializer,
    TermsReplaceInputSerializer,
)

# 401, 403, 404 and 429 with the Problem body are added to every operation by core.schema.
INVALID = OpenApiResponse(ProblemSerializer, "Invalid input, named by its field")
ERASED = OpenApiResponse(ProblemSerializer, "contact_erased: the depositor's contact was erased")
TAKEN = OpenApiResponse(ProblemSerializer, "mta_version_taken: published at the same moment")
STATE = OpenApiResponse(
    ProblemSerializer,
    "deposit_state: the deposit is no longer in the state the action starts from;"
    " terms_changed; accession_taken",
)
RULE = OpenApiResponse(
    ProblemSerializer,
    "lab_authorisation_required: the lab holds no valid permit for a restriction's kind;"
    " reason_required",
)
ACCEPT_INVALID = OpenApiResponse(
    ProblemSerializer, "Invalid input, an unknown taxon, or a risk group 4 agent (on risk_group)"
)
LAB_PARAMETER = OpenApiParameter("lab_public_id", OpenApiTypes.UUID, OpenApiParameter.PATH)


def _input(serializer: type[Serializer[None]], view: "LabNested", request: Request) -> Any:
    data = serializer(data=request.data, context=view.get_serializer_context())
    data.is_valid(raise_exception=True)
    return data.validated_data


def _terms(values: dict[str, Any]) -> services.TermsInput:
    return services.TermsInput(
        abs_scope=AbsScope(values["abs_scope"]),
        uses=[(Use(u["use"]), Decision(u["decision"])) for u in values["uses"]],
        mta=values["mta"],
        country_of_origin=values["country_of_origin"],
        collection_date=values["collection_date"],
        pic_reference=values["pic_reference"],
        mat_reference=values["mat_reference"],
        ircc=values["ircc"],
        permit_reference=values["permit_reference"],
        mat_uses=[Use(use) for use in values["mat_uses"]],
    )


def _contact(values: dict[str, Any]) -> services.ContactInput:
    return services.ContactInput(
        name=values["name"], email=values["email"], postal_address=values["postal_address"]
    )


# The resources of one lab, nested under it. The lab comes from the URL and is resolved
# through the caller's labs first: not a member gives 404 for every action, before any role
# check or input validation. Curators and managers read and write (deposits.view,
# deposits.manage), managers publish MTA versions (deposits.manage_mta); the services
# re-read the role under the lab lock. Nothing here is deleted.
# (Comments, not docstrings: a docstring becomes the description of every operation.)
class LabNested(ScopedReadOnlyViewSet, abstract=True):
    @cached_property
    def lab(self) -> Lab:
        return labs.lab_get(access=access_of(self.request), public_id=self.kwargs["lab_public_id"])

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        lab_id = getattr(obj, "lab_id", None) if obj is not None else self.lab.pk
        return lab_id is not None and access_of(self.request).can(Perm(perm), lab_id)


@extend_schema(parameters=[LAB_PARAMETER])
class DepositorViewSet(LabNested):
    action_perms = {
        "list": Perm.VIEW_DEPOSITS,
        "retrieve": Perm.VIEW_DEPOSITS,
        "create": Perm.MANAGE_DEPOSITS,
        "update": Perm.MANAGE_DEPOSITS,
    }
    serializer_class = DepositorOutputSerializer
    filterset_class = DepositorFilter

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.depositor_list(access=access_of(self.request), lab=self.lab)

    def _detail(self, depositor: Depositor) -> Response:
        fresh = self.scoped_queryset().get(pk=depositor.pk)
        return Response(DepositorOutputSerializer(fresh).data)

    @extend_schema(
        request=DepositorInputSerializer,
        responses={201: DepositorOutputSerializer, (400, PROBLEM): INVALID},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab  # first: an outsider gets 404, never a 400 that reveals the lab
        values = _input(DepositorInputSerializer, self, request)
        depositor = services.depositor_create(
            access=access_of(request),
            lab=lab,
            contact=_contact(values),
            institution=values["institution"],
        )
        response = self._detail(depositor)
        response.status_code = status.HTTP_201_CREATED
        return response

    @extend_schema(
        request=DepositorInputSerializer,
        responses={200: DepositorOutputSerializer, (400, PROBLEM): INVALID, (409, PROBLEM): ERASED},
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        depositor: Depositor = self.get_object()  # first: 404 or 403 before the input is read
        values = _input(DepositorInputSerializer, self, request)
        services.depositor_update(
            access=access_of(request),
            depositor=depositor,
            contact=_contact(values),
            institution=values["institution"],
        )
        return self._detail(depositor)


@extend_schema(parameters=[LAB_PARAMETER])
class MtaTemplateViewSet(LabNested):
    action_perms = {
        "list": Perm.VIEW_DEPOSITS,
        "retrieve": Perm.VIEW_DEPOSITS,
        "create": Perm.MANAGE_MTA,
    }

    def get_serializer_class(self) -> type[MtaTemplateListOutputSerializer]:
        if self.action == "list":
            return MtaTemplateListOutputSerializer
        return MtaTemplateDetailOutputSerializer

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.mta_template_list(access=access_of(self.request), lab=self.lab)

    @extend_schema(
        request=MtaTemplateInputSerializer,
        responses={
            201: MtaTemplateDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): TAKEN,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab
        values = _input(MtaTemplateInputSerializer, self, request)
        template = services.mta_template_publish(
            access=access_of(request),
            lab=lab,
            code=values["code"],
            title=values["title"],
            text=values["text"],
        )
        return Response(
            MtaTemplateDetailOutputSerializer(template).data, status=status.HTTP_201_CREATED
        )


# The views that take a file read multipart; every other view reads JSON only (#41).
UPLOAD_PARSERS = [MultiPartParser, LimitedJSONParser]
CATALOGUE_REFUSED = OpenApiResponse(
    ProblemSerializer,
    "catalogue_refused: not a CSV UTF-8 in the template's columns, too large or empty;"
    " catalogue_changed: not the file that was checked; catalogue_has_errors: a row failed,"
    " nothing was imported",
)


def _catalogue_file(values: dict[str, Any]) -> bytes:
    """The file's bytes, refused before they are read when it is too large."""
    upload = values["file"]
    if upload.size is not None and upload.size > catalogue.MAX_BYTES:
        raise catalogue.CatalogueRefused(
            f"The file is larger than {catalogue.MAX_BYTES // (1024 * 1024)} MB.", attr="file"
        )
    return b"".join(upload.chunks())


@extend_schema(parameters=[LAB_PARAMETER])
class DepositViewSet(LabNested):
    action_perms = {
        "list": Perm.VIEW_DEPOSITS,
        "retrieve": Perm.VIEW_DEPOSITS,
        "create": Perm.MANAGE_DEPOSITS,
        "replace_terms": Perm.MANAGE_DEPOSITS,
        "start_check": Perm.MANAGE_DEPOSITS,
        "accept": Perm.MANAGE_DEPOSITS,
        "reject": Perm.MANAGE_DEPOSITS,
        "catalogue_template": Perm.IMPORT_CATALOGUE,
        "catalogue_check": Perm.IMPORT_CATALOGUE,
        "catalogue_import": Perm.IMPORT_CATALOGUE,
    }
    filterset_class = DepositFilter

    def get_serializer_class(self) -> type[DepositListOutputSerializer]:
        if self.action == "list":
            return DepositListOutputSerializer
        return DepositDetailOutputSerializer

    def scoped_queryset(self) -> QuerySet[Any]:
        access = access_of(self.request)
        if self.action == "list":
            return selectors.deposit_list(access=access, lab=self.lab)
        return selectors.deposit_detail(access=access, lab=self.lab)

    def _detail(self, deposit: Deposit) -> Response:
        fresh = selectors.deposit_detail(access=access_of(self.request), lab=self.lab).get(
            pk=deposit.pk
        )
        return Response(DepositDetailOutputSerializer(fresh).data)

    @extend_schema(
        request=DepositReceiveInputSerializer,
        responses={201: DepositDetailOutputSerializer, (400, PROBLEM): INVALID},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab
        values = _input(DepositReceiveInputSerializer, self, request)
        deposit = services.deposit_receive(
            access=access_of(request),
            lab=lab,
            data=services.NewDeposit(
                depositor=values["depositor"],
                received_on=values["received_on"],
                condition=Condition(values["condition"]),
                condition_note=values["condition_note"],
                name_as_received=values["name_as_received"],
                depositor_passages=values["depositor_passages"],
                terms=_terms(values["terms"]),
            ),
        )
        response = self._detail(deposit)
        response.status_code = status.HTTP_201_CREATED
        return response

    @extend_schema(
        request=TermsReplaceInputSerializer,
        responses={
            200: DepositDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): STATE,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="terms")
    def replace_terms(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        deposit: Deposit = self.get_object()
        values = _input(TermsReplaceInputSerializer, self, request)
        services.deposit_terms_replace(
            access=access_of(request),
            deposit=deposit,
            terms=_terms(values["terms"]),
            reason=values["reason"],
        )
        return self._detail(deposit)

    @extend_schema(
        request=None, responses={200: DepositDetailOutputSerializer, (409, PROBLEM): STATE}
    )
    @action(detail=True, methods=["post"], url_path="start-check")
    def start_check(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        deposit: Deposit = self.get_object()
        services.deposit_start_check(access=access_of(request), deposit=deposit)
        return self._detail(deposit)

    @extend_schema(
        request=StrainFactsInputSerializer,
        responses={
            200: DepositDetailOutputSerializer,
            (400, PROBLEM): ACCEPT_INVALID,
            (409, PROBLEM): STATE,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="accept")
    def accept(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        deposit: Deposit = self.get_object()
        values = _input(StrainFactsInputSerializer, self, request)
        services.deposit_accept(
            access=access_of(request),
            deposit=deposit,
            facts=services.StrainFacts(
                taxon=values["taxon"],
                identified_on=values["identified_on"],
                identification_method=values["identification_method"],
                risk_group=values["risk_group"],
                risk_group_basis=values["risk_group_basis"],
                risk_group_entry=values["risk_group_basis_entry"],
                animal_pathogenicity=Pathogenicity(values["animal_pathogenicity"]),
                plant_pathogenicity=Pathogenicity(values["plant_pathogenicity"]),
                isolation_source=values["isolation_source"],
                country_of_origin=values["country_of_origin"],
                isolation_date=values["isolation_date"],
                restrictions=[
                    strains.RestrictionInput(
                        kind=RestrictionKind(item["kind"]),
                        reference=item["reference"],
                        act=item["act"],
                        gmo_category=item["gmo_category"],
                    )
                    for item in values["restrictions"]
                ],
            ),
        )
        return self._detail(deposit)

    @extend_schema(responses={(200, "text/csv"): OpenApiTypes.STR})
    @action(detail=False, methods=["get"], url_path="catalogue-template")
    def catalogue_template(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        """The CSV file to fill in for a catalogue import (#70): the header and one example."""
        self.lab  # noqa: B018 (a lab the caller is not in is a 404, as for every lab view)
        response = HttpResponse(catalogue.template(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="catalogue-template.csv"'
        return response

    @extend_schema(
        request={"multipart/form-data": CatalogueCheckInputSerializer},
        responses={
            200: CatalogueCheckOutputSerializer,
            (400, PROBLEM): INVALID,
            (422, PROBLEM): CATALOGUE_REFUSED,
        },
    )
    @action(
        detail=False, methods=["post"], url_path="catalogue-check", parser_classes=UPLOAD_PARSERS
    )
    def catalogue_check(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Every row tried, every error reported, nothing written (#70)."""
        values = _input(CatalogueCheckInputSerializer, self, request)
        checked = catalogue.catalogue_check(
            access=access_of(request), lab=self.lab, content=_catalogue_file(values)
        )
        return Response(CatalogueCheckOutputSerializer(checked).data)

    @extend_schema(
        request={"multipart/form-data": CatalogueImportInputSerializer},
        responses={
            201: CatalogueImportOutputSerializer,
            (400, PROBLEM): INVALID,
            (422, PROBLEM): CATALOGUE_REFUSED,
        },
    )
    @action(
        detail=False, methods=["post"], url_path="catalogue-import", parser_classes=UPLOAD_PARSERS
    )
    def catalogue_import(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The checked file, all rows or none (#70)."""
        values = _input(CatalogueImportInputSerializer, self, request)
        created = catalogue.catalogue_import(
            access=access_of(request),
            lab=self.lab,
            content=_catalogue_file(values),
            sha256=values["sha256"],
            reason=values["reason"],
        )
        return Response(
            CatalogueImportOutputSerializer({"strains": created}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=RejectInputSerializer,
        responses={
            200: DepositDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): STATE,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        deposit: Deposit = self.get_object()
        values = _input(RejectInputSerializer, self, request)
        services.deposit_reject(access=access_of(request), deposit=deposit, reason=values["reason"])
        return self._detail(deposit)

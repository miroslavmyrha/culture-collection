from functools import cached_property
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db.models import Model, QuerySet
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer

from cultures.biosafety.policy import permit_today
from cultures.core.api import ScopedViewSetMixin
from cultures.core.errors import PROBLEM_CONTENT_TYPE as PROBLEM
from cultures.core.errors import ProblemSerializer
from cultures.deposits.models import Use
from cultures.distribution import policy, selectors, services
from cultures.distribution.filters import PermitFilter, RequesterFilter, RequestFilter
from cultures.distribution.models import (
    MAX_DOCUMENT_BYTES,
    DistributionRequest,
    Document,
    LegalForm,
    PermitKind,
    RecipientPermit,
    Requester,
    RequestStatus,
    SignerRole,
)
from cultures.labs import selectors as labs
from cultures.labs.access import access_of
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm

from .serializers import (
    AcceptanceInputSerializer,
    ApproveInputSerializer,
    PermitEndInputSerializer,
    PermitInputSerializer,
    PermitOutputSerializer,
    ReasonInputSerializer,
    RequestDetailOutputSerializer,
    RequesterInputSerializer,
    RequesterOutputSerializer,
    RequestInputSerializer,
    RequestListOutputSerializer,
)

# 401, 403, 404 and 429 with the Problem body are added to every operation by core.schema.
INVALID = OpenApiResponse(
    ProblemSerializer,
    "Invalid input, named by its field: an unknown requester, strain or MTA version, a strain"
    " without terms (no_terms), a file that is empty, too large or not a PDF, PNG or JPEG",
)
STATE = OpenApiResponse(
    ProblemSerializer,
    "request_state: the request is no longer in the state the action starts from;"
    " acceptance_exists; permit_ended; contact_erased; not_enough_vials;"
    " vial_reserved_meanwhile; request_number_taken",
)
BLOCKED = OpenApiResponse(
    ProblemSerializer,
    "request_blocked: a finding of the policy blocks the approval (the detail lists them);"
    " reason_required",
)
DESTINATION = OpenApiResponse(
    ProblemSerializer,
    "export_of_regulated_strain, export_not_supported: the requester is outside the EU",
)
RULE = OpenApiResponse(ProblemSerializer, "reason_required")
LAB_PARAMETER = OpenApiParameter("lab_public_id", OpenApiTypes.UUID, OpenApiParameter.PATH)


def _input(serializer: type[Serializer[None]], view: Any, request: Request) -> Any:
    data = serializer(data=request.data, context=view.get_serializer_context())
    data.is_valid(raise_exception=True)
    return data.validated_data


def _content(upload: UploadedFile[bytes]) -> services.DocumentInput:
    """The file's bytes, refused before they are read when the upload is too large."""
    if upload.size is not None and upload.size > MAX_DOCUMENT_BYTES:
        raise services.InvalidDistribution(
            f"The file is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB.", attr="file"
        )
    return services.DocumentInput(content=b"".join(upload.chunks()))


def _requester(values: dict[str, Any]) -> services.RequesterInput:
    return services.RequesterInput(
        contact=services.ContactInput(
            name=values["name"], email=values["email"], postal_address=values["postal_address"]
        ),
        institution=values["institution"],
        legal_form=LegalForm(values["legal_form"]),
        country=values["country"],
        lab_evidence=values["lab_evidence"],
        lab_confirmed_on=values["lab_confirmed_on"],
        registration_number=values["registration_number"],
    )


# The resources of one lab, nested under it. The lab comes from the URL and is resolved
# through the caller's labs first: not a member gives 404 for every action, before any role
# check or input validation. The services re-read the role under the lab lock. Nothing here is
# deleted. (Comments, not docstrings: a docstring becomes the description of every operation.)
class LabScoped(ScopedViewSetMixin, abstract=True):
    @cached_property
    def lab(self) -> Lab:
        return labs.lab_get(access=access_of(self.request), public_id=self.kwargs["lab_public_id"])

    def has_perm(self, perm: str, obj: Model | None) -> bool:
        lab_id = getattr(obj, "lab_id", None) if obj is not None else self.lab.pk
        return lab_id is not None and access_of(self.request).can(Perm(perm), lab_id)


class LabNested(LabScoped, viewsets.ReadOnlyModelViewSet, abstract=True):  # type: ignore[type-arg]
    pass


# Requesters: institutions that may receive material, with the responsible scientist and the
# delivery address (a contact). Curators and managers read and write them (they reach people).
@extend_schema(parameters=[LAB_PARAMETER])
class RequesterViewSet(LabNested):
    action_perms = {
        "list": Perm.VIEW_REQUESTERS,
        "retrieve": Perm.VIEW_REQUESTERS,
        "create": Perm.MANAGE_DISTRIBUTION,
        "update": Perm.MANAGE_DISTRIBUTION,
    }
    serializer_class = RequesterOutputSerializer
    filterset_class = RequesterFilter

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.requester_list(access=access_of(self.request), lab=self.lab)

    def _detail(self, requester: Requester, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.scoped_queryset().get(pk=requester.pk)
        return Response(RequesterOutputSerializer(fresh).data, status=code)

    @extend_schema(
        request=RequesterInputSerializer,
        responses={201: RequesterOutputSerializer, (400, PROBLEM): INVALID},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab  # first: an outsider gets 404, never a 400 that reveals the lab
        values = _input(RequesterInputSerializer, self, request)
        requester = services.requester_create(
            access=access_of(request), lab=lab, data=_requester(values)
        )
        return self._detail(requester, status.HTTP_201_CREATED)

    @extend_schema(
        request=RequesterInputSerializer,
        responses={200: RequesterOutputSerializer, (400, PROBLEM): INVALID, (409, PROBLEM): STATE},
    )
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        requester: Requester = self.get_object()  # first: 404 or 403 before the input is read
        values = _input(RequesterInputSerializer, self, request)
        services.requester_update(
            access=access_of(request), requester=requester, data=_requester(values)
        )
        return self._detail(requester)


# The documents a requester holds (permits, notices, letters), each with its file. Curators
# record and end them; nothing is deleted.
@extend_schema(parameters=[LAB_PARAMETER])
class PermitViewSet(LabNested):
    action_perms = {
        "list": Perm.VIEW_REQUESTERS,
        "retrieve": Perm.VIEW_REQUESTERS,
        "create": Perm.MANAGE_DISTRIBUTION,
        "end": Perm.MANAGE_DISTRIBUTION,
    }
    serializer_class = PermitOutputSerializer
    filterset_class = PermitFilter

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.permit_list(access=access_of(self.request), lab=self.lab)

    def _detail(self, permit: RecipientPermit, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.scoped_queryset().get(pk=permit.pk)
        return Response(PermitOutputSerializer(fresh).data, status=code)

    @extend_schema(
        request={"multipart/form-data": PermitInputSerializer},
        responses={201: PermitOutputSerializer, (400, PROBLEM): INVALID},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab
        values = _input(PermitInputSerializer, self, request)
        permit = services.permit_add(
            access=access_of(request),
            requester=values["requester"],
            data=services.PermitInput(
                kind=PermitKind(values["kind"]),
                issuer=values["issuer"],
                issuer_country=values["issuer_country"],
                reference=values["reference"],
                valid_from=values["valid_from"],
                document=_content(values["file"]),
                expires_on=values["expires_on"],
                covers=values["covers"],
                quantity_allowed=values["quantity_allowed"],
                sendings_allowed=values["sendings_allowed"],
                endorsement_reference=values["endorsement_reference"],
                endorsed_on=values["endorsed_on"],
                gmo_category=values["gmo_category"],
                risk_group=values["risk_group"],
            ),
        )
        assert permit.lab_id == lab.pk  # noqa: S101 (the requester was resolved in this lab)
        return self._detail(permit, status.HTTP_201_CREATED)

    @extend_schema(
        request=PermitEndInputSerializer,
        responses={
            200: PermitOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): STATE,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="end")
    def end(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        permit: RecipientPermit = self.get_object()
        values = _input(PermitEndInputSerializer, self, request)
        services.permit_end(
            access=access_of(request),
            permit=permit,
            ended_on=values["ended_on"],
            reason=values["reason"],
        )
        return self._detail(permit)


# A document's file, for a caller who may view requesters: as an attachment, never shown in
# the browser, named by its public id (no file name is kept), not cached.
@extend_schema(parameters=[LAB_PARAMETER])
class DocumentViewSet(LabScoped, mixins.RetrieveModelMixin):
    action_perms = {"retrieve": Perm.VIEW_REQUESTERS}
    serializer_class = PermitOutputSerializer  # for the schema generator only

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.document_list(access=access_of(self.request), lab=self.lab)

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:  # type: ignore[override]
        document: Document = self.get_object()
        extension = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}
        response = HttpResponse(bytes(document.content), content_type=document.content_type)
        name = f"document-{document.public_id}.{extension[document.content_type]}"
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


# Requests: what a requester asks for, with its lines. Viewers and up read (no person, no
# place); curators enter, approve, reject and cancel them; an approval over a finding that
# needs a manager (a regulated line above all) needs a manager and a reason.
@extend_schema(parameters=[LAB_PARAMETER])
class RequestViewSet(LabNested):
    action_perms = {
        "list": Perm.VIEW_DISTRIBUTION,
        "retrieve": Perm.VIEW_DISTRIBUTION,
        "create": Perm.MANAGE_DISTRIBUTION,
        "approve": Perm.MANAGE_DISTRIBUTION,
        "reject": Perm.MANAGE_DISTRIBUTION,
        "cancel": Perm.MANAGE_DISTRIBUTION,
        "acceptances": Perm.MANAGE_DISTRIBUTION,
    }
    filterset_class = RequestFilter

    def get_serializer_class(self) -> type[RequestListOutputSerializer]:
        if self.action == "list":
            return RequestListOutputSerializer
        return RequestDetailOutputSerializer

    def scoped_queryset(self) -> QuerySet[Any]:
        access = access_of(self.request)
        if self.action == "list":
            return selectors.request_list(access=access, lab=self.lab)
        return selectors.request_detail(access=access, lab=self.lab)

    def get_serializer_context(self) -> dict[str, Any]:
        context = dict(super().get_serializer_context())
        context["show_people"] = access_of(self.request).can(Perm.VIEW_REQUESTERS, self.lab.pk)
        return context

    def _detail(self, request: DistributionRequest, code: int = status.HTTP_200_OK) -> Response:
        """The request as committed now, read again after a write."""
        fresh = selectors.request_detail(access=access_of(self.request), lab=self.lab).get(
            pk=request.pk
        )
        return self._answer(fresh, code)

    def _answer(self, fresh: DistributionRequest, code: int = status.HTTP_200_OK) -> Response:
        context = self.get_serializer_context()
        if fresh.status == RequestStatus.SUBMITTED:
            context["findings"] = policy.evaluate(fresh, permit_today()).findings
        return Response(RequestDetailOutputSerializer(fresh, context=context).data, status=code)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._answer(self.get_object())  # loaded through request_detail already

    @extend_schema(
        request=RequestInputSerializer,
        responses={
            201: RequestDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): STATE,
            (422, PROBLEM): DESTINATION,
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        lab = self.lab
        values = _input(RequestInputSerializer, self, request)
        created = services.request_submit(
            access=access_of(request),
            lab=lab,
            data=services.NewRequest(
                requester=values["requester"],
                use=Use(values["use"]),
                end_use=values["end_use"],
                containment_level=values["containment_level"],
                lines=[
                    services.LineInput(strain=line["strain"], quantity=line["quantity"])
                    for line in values["lines"]
                ],
            ),
        )
        return self._detail(created, status.HTTP_201_CREATED)

    @extend_schema(
        request=ApproveInputSerializer,
        responses={
            200: RequestDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): STATE,
            (422, PROBLEM): BLOCKED,
        },
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        target: DistributionRequest = self.get_object()
        values = _input(ApproveInputSerializer, self, request)
        services.request_approve(access=access_of(request), request=target, reason=values["reason"])
        return self._detail(target)

    @extend_schema(
        request=ReasonInputSerializer,
        responses={
            200: RequestDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): STATE,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        target: DistributionRequest = self.get_object()
        values = _input(ReasonInputSerializer, self, request)
        services.request_reject(access=access_of(request), request=target, reason=values["reason"])
        return self._detail(target)

    @extend_schema(
        request=ReasonInputSerializer,
        responses={
            200: RequestDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): STATE,
            (422, PROBLEM): RULE,
        },
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        target: DistributionRequest = self.get_object()
        values = _input(ReasonInputSerializer, self, request)
        services.request_cancel(access=access_of(request), request=target, reason=values["reason"])
        return self._detail(target)

    @extend_schema(
        request={"multipart/form-data": AcceptanceInputSerializer},
        responses={
            201: RequestDetailOutputSerializer,
            (400, PROBLEM): INVALID,
            (409, PROBLEM): STATE,
        },
    )
    @action(detail=True, methods=["post"], url_path="acceptances")
    def acceptances(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        target: DistributionRequest = self.get_object()
        values = _input(AcceptanceInputSerializer, self, request)
        services.acceptance_record(
            access=access_of(request),
            request=target,
            data=services.AcceptanceInput(
                mta_id=values["mta"].pk,
                signer=services.ContactInput(
                    name=values["signer_name"], email=values["signer_email"]
                ),
                signer_role=SignerRole(values["signer_role"]),
                authorised_signatory=values["authorised_signatory"],
                accepted_on=values["accepted_on"],
                document=_content(values["file"]),
            ),
        )
        return self._detail(target, status.HTTP_201_CREATED)

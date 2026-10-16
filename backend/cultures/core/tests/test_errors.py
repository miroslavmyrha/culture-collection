"""Every error has the one problem-details shape (cultures.core.errors)."""

import importlib
import pkgutil
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from django.test import Client, RequestFactory, override_settings
from django.urls import get_resolver
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

import cultures
from cultures.core import exceptions as domain
from cultures.core.testing import assert_problem
from cultures.users.api.views import LoginThrottle

pytestmark = pytest.mark.django_db


class ItemSerializer(serializers.Serializer[None]):
    name = serializers.CharField()
    tags = serializers.ListField(child=serializers.CharField(max_length=3))


class OrderSerializer(serializers.Serializer[None]):
    items = ItemSerializer(many=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        raise serializers.ValidationError("Whole order is wrong.", code="order_rule")


@api_view(["POST"])
@permission_classes([AllowAny])
def validating_view(request: Request) -> Response:
    OrderSerializer(data=request.data).is_valid(raise_exception=True)
    return Response()


def raising_view(exc: Exception) -> Any:
    @api_view(["GET"])
    @permission_classes([AllowAny])
    def view(request: Request) -> Response:
        raise exc

    return view


def call(view: Any, method: str = "get", data: Any = None) -> Any:
    factory = APIRequestFactory()
    request = getattr(factory, method)("/x/", data, format="json")
    response = view(request)
    response.render()
    return response


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (domain.NotFound(), 404, "not_found"),
        (domain.Forbidden(), 403, "permission_denied"),
        (domain.Conflict("Already placed."), 409, "conflict"),
        (domain.PreconditionFailed(), 412, "precondition_failed"),
        (domain.RuleViolation("Box is full.", code="box_full"), 422, "box_full"),
    ],
)
def test_domain_exceptions_map_to_status(exc: domain.DomainError, status: int, code: str) -> None:
    body = assert_problem(call(raising_view(exc)), status, code)
    assert body["detail"] == exc.detail


def project_domain_errors() -> list[type[domain.DomainError]]:
    """Every DomainError subclass in the project, after importing all its modules."""
    for module in pkgutil.walk_packages(cultures.__path__, "cultures."):
        if not {"tests", "testing", "migrations"} & set(module.name.split(".")):
            importlib.import_module(module.name)
    found: list[type[domain.DomainError]] = []
    pending = [domain.DomainError]
    while pending:
        children = pending.pop().__subclasses__()
        pending += children
        found += [cls for cls in children if ".tests." not in cls.__module__]
    return sorted(found, key=lambda cls: f"{cls.__module__}.{cls.__qualname__}")


DOMAIN_ERRORS = project_domain_errors()


def test_the_domain_error_walk_finds_the_core_exceptions() -> None:
    core = {domain.NotFound, domain.Forbidden, domain.Conflict}
    core |= {domain.PreconditionFailed, domain.RuleViolation}
    assert core <= set(DOMAIN_ERRORS)  # an empty walk must not pass


@pytest.mark.parametrize("error", DOMAIN_ERRORS, ids=lambda cls: cls.__qualname__)
def test_every_domain_error_maps_to_its_status_and_code(error: type[domain.DomainError]) -> None:
    body = assert_problem(call(raising_view(error())), error.status_code, error.default_code)
    assert body["detail"] == error.default_detail


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (Http404(), 404, "not_found"),  # get_object_or_404 in a view or a service
        (DjangoPermissionDenied(), 403, "permission_denied"),
    ],
)
def test_django_exceptions_in_a_view_get_the_problem_shape(
    exc: Exception, status: int, code: str
) -> None:
    assert_problem(call(raising_view(exc)), status, code)


def test_domain_exception_with_attr_lists_the_field() -> None:
    exc = domain.RuleViolation("Position taken.", code="position_taken", attr="position")
    body = assert_problem(call(raising_view(exc)), 422, "position_taken")
    assert body["errors"] == [
        {"attr": "position", "code": "position_taken", "detail": "Position taken."}
    ]


def test_nested_validation_errors_are_flat_with_dotted_paths() -> None:
    data = {"items": [{"name": "ok", "tags": ["fine"]}, {"tags": ["toolong"]}]}
    body = assert_problem(call(validating_view, "post", data), 400, "invalid")
    attrs = {(e["attr"], e["code"]) for e in body["errors"]}
    assert ("items.0.tags.0", "max_length") in attrs
    assert ("items.1.name", "required") in attrs


def test_non_field_errors_have_a_null_attr() -> None:
    body = assert_problem(call(validating_view, "post", {"items": []}), 400, "invalid")
    assert body["errors"] == [
        {"attr": None, "code": "order_rule", "detail": "Whole order is wrong."}
    ]


def test_django_validation_error_from_a_service_is_a_400() -> None:
    exc = DjangoValidationError({"barcode": ["Bad checksum."]}, code="checksum")
    body = assert_problem(call(raising_view(exc)), 400, "invalid")
    assert body["errors"][0]["attr"] == "barcode"


def test_unknown_exceptions_stay_500s() -> None:
    with pytest.raises(RuntimeError):
        call(raising_view(RuntimeError("bug")))


def test_401_for_anonymous_with_a_challenge(client: Client) -> None:
    response = client.get("/api/v1/auth/me/")
    assert_problem(response, 401, "not_authenticated")
    assert response["WWW-Authenticate"] == 'Session realm="api"'


def test_403_for_csrf_failure() -> None:
    response = Client(enforce_csrf_checks=True).post(
        "/api/v1/auth/login/", {"username": "a", "password": "b"}, content_type="application/json"
    )
    assert_problem(response, 403, "permission_denied")


def test_404_outside_drf_has_the_same_shape(client: Client) -> None:
    assert_problem(client.get("/api/v1/does-not-exist/"), 404, "not_found")


# Django has a handler for each of these statuses (django.urls.resolvers.
# URLResolver.resolve_error_handler); config/urls.py must replace all of them.
@pytest.mark.parametrize(
    ("status", "code", "args"),
    [
        (400, "bad_request", (None,)),
        (403, "permission_denied", (None,)),
        (404, "not_found", (None,)),
        (500, "server_error", ()),  # handler500 takes no exception
    ],
)
def test_every_installed_error_handler_answers_a_problem(
    rf: RequestFactory, status: int, code: str, args: tuple[None, ...]
) -> None:
    handler = get_resolver().resolve_error_handler(status)
    assert_problem(handler(rf.get("/x/"), *args), status, code)


def test_429_keeps_retry_after(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LoginThrottle, "rate", "1/min", raising=False)
    payload = {"username": "a", "password": "b"}
    client.post("/api/v1/auth/login/", payload, content_type="application/json")
    response = client.post("/api/v1/auth/login/", payload, content_type="application/json")
    assert_problem(response, 429, "throttled")
    assert int(response["Retry-After"]) > 0


@override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1024)
def test_json_body_over_the_limit_is_413(client: Client) -> None:
    # DRF >= 3.17.2 parses JSON from request.body, where Django checks the limit
    # first. The parser's own cap is a second line, tested in test_parsers.py.
    payload = {"username": "a", "password": "x" * 2000}
    response = client.post("/api/v1/auth/login/", payload, content_type="application/json")
    assert_problem(response, 413, "request_too_large")


def test_json_body_under_the_limit_is_parsed(client: Client) -> None:
    response = client.post(
        "/api/v1/auth/login/", {"username": "a", "password": "b"}, content_type="application/json"
    )
    assert_problem(response, 400, "invalid_credentials")


def test_schema_declares_the_shared_problem_component(client: Client) -> None:
    from drf_spectacular.generators import SchemaGenerator  # noqa: PLC0415

    generator = SchemaGenerator()  # type: ignore[no-untyped-call]
    schema = generator.get_schema(request=None, public=True)  # type: ignore[no-untyped-call]
    assert "Problem" in schema["components"]["schemas"]
    me = schema["paths"]["/api/v1/auth/me/"]["get"]["responses"]
    ref = me["401"]["content"]["application/problem+json"]["schema"]["$ref"]
    assert ref == "#/components/schemas/Problem"
    login = schema["paths"]["/api/v1/auth/login/"]["post"]["responses"]
    assert {"400", "403", "429"} <= set(login)

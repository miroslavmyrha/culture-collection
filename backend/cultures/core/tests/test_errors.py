"""Every error has the one problem-details shape (cultures.core.errors)."""

import json
from typing import Any

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import Client, override_settings
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from cultures.core import exceptions as domain
from cultures.users.api.views import LoginThrottle

pytestmark = pytest.mark.django_db
PROBLEM_KEYS = {"type", "title", "status", "detail", "code", "errors"}


def assert_problem(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.content
    assert response["Content-Type"] == "application/problem+json"
    body: dict[str, Any] = json.loads(response.content)
    assert set(body) == PROBLEM_KEYS
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == "about:blank"
    return body


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


def test_429_keeps_retry_after(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LoginThrottle, "rate", "1/min", raising=False)
    payload = {"username": "a", "password": "b"}
    client.post("/api/v1/auth/login/", payload, content_type="application/json")
    response = client.post("/api/v1/auth/login/", payload, content_type="application/json")
    assert_problem(response, 429, "throttled")
    assert int(response["Retry-After"]) > 0


@override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1024)
def test_json_body_over_the_limit_is_413() -> None:
    # DRF reads JSON from the stream, past Django's check: the parser enforces it.
    data = {"items": [{"name": "x" * 2000, "tags": []}]}
    assert_problem(call(validating_view, "post", data), 413, "request_too_large")


@override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1024)
def test_body_over_the_limit_read_by_django_is_413_too(client: Client) -> None:
    # Login reads the body for the CSRF check first, so Django's own check fires.
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

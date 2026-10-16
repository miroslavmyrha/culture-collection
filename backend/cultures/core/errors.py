"""One error shape for the whole API, problem details style (RFC 9457).

    {"type": "about:blank", "title": "Not Found", "status": 404,
     "detail": "Not found.", "code": "not_found",
     "errors": [{"attr": "username", "code": "required", "detail": "..."}]}

Content-Type is application/problem+json. `code` is stable and meant for
programs, `detail` for people. `errors` lists field errors (attr is a dotted
path such as "items.0.name", null for errors about the whole input); it is
empty for other errors. Domain exceptions from services map here to their
status. Unknown exceptions are not caught: they stay 500s and reach the logs
and error reporting.
"""

from http import HTTPStatus
from typing import Any

from django.core.exceptions import NON_FIELD_ERRORS, RequestDataTooBig
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404, HttpRequest, JsonResponse
from rest_framework import exceptions, serializers
from rest_framework.fields import get_error_detail
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.views import set_rollback

from .exceptions import DomainError
from .parsers import RequestTooLarge

PROBLEM_CONTENT_TYPE = "application/problem+json"


def problem(
    status: int, code: str, detail: str, errors: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "code": code,
        "errors": errors or [],
    }


def flatten_errors(detail: Any, attr: str | None = None) -> list[dict[str, Any]]:
    """Nested DRF error details to a flat list of {attr, code, detail}."""
    if isinstance(detail, dict):
        items: list[dict[str, Any]] = []
        for key, value in detail.items():
            if key in {api_settings.NON_FIELD_ERRORS_KEY, NON_FIELD_ERRORS}:
                child = attr
            else:
                child = f"{attr}.{key}" if attr else str(key)
            items.extend(flatten_errors(value, child))
        return items
    if isinstance(detail, list):
        items = []
        for index, value in enumerate(detail):
            # A list of messages belongs to attr; a list of objects is indexed.
            child = f"{attr}.{index}" if attr and isinstance(value, dict | list) else attr
            items.extend(flatten_errors(value, child))
        return items
    return [{"attr": attr, "code": getattr(detail, "code", "invalid"), "detail": str(detail)}]


def _as_api_exception(exc: Exception) -> Exception:
    if isinstance(exc, RequestDataTooBig):
        return RequestTooLarge()
    if isinstance(exc, Http404):
        return exceptions.NotFound()
    if isinstance(exc, DjangoPermissionDenied):
        return exceptions.PermissionDenied()
    if isinstance(exc, DjangoValidationError):
        # Model full_clean() or a validator in a service: same shape as serializer errors.
        return exceptions.ValidationError(detail=get_error_detail(exc))
    return exc


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, DomainError):
        set_rollback()
        errors = [{"attr": exc.attr, "code": exc.code, "detail": exc.detail}] if exc.attr else []
        domain_response = Response(
            problem(exc.status_code, exc.code, exc.detail, errors), status=exc.status_code
        )
        domain_response.content_type = PROBLEM_CONTENT_TYPE
        return domain_response

    exc = _as_api_exception(exc)
    response = drf_exception_handler(
        exc, context
    )  # headers (WWW-Authenticate, Retry-After), rollback
    if response is None or not isinstance(exc, exceptions.APIException):
        return response
    if isinstance(exc, exceptions.ValidationError):
        data = problem(
            response.status_code, "invalid", "Invalid input.", flatten_errors(exc.detail)
        )
    else:
        code = exc.get_codes()
        data = problem(
            response.status_code,
            code if isinstance(code, str) else exc.default_code,
            str(exc.detail),
        )
    response.data = data
    response.content_type = PROBLEM_CONTENT_TYPE
    return response


# Django-level handlers for requests that never reach a DRF view (unknown URLs,
# DisallowedHost, crashes in middleware). config/urls.py installs them.
def _django_problem(status: int, code: str, detail: str) -> JsonResponse:
    return JsonResponse(
        problem(status, code, detail), status=status, content_type=PROBLEM_CONTENT_TYPE
    )


def bad_request(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    if isinstance(exception, RequestDataTooBig):
        return _django_problem(
            413, RequestTooLarge.default_code, str(RequestTooLarge.default_detail)
        )
    return _django_problem(400, "bad_request", "Bad request.")


def permission_denied(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return _django_problem(403, "permission_denied", "Permission denied.")


def not_found(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return _django_problem(404, "not_found", "Not found.")


def server_error(request: HttpRequest) -> JsonResponse:
    return _django_problem(500, "server_error", "Internal server error.")


class ProblemFieldErrorSerializer(serializers.Serializer[None]):
    attr = serializers.CharField(allow_null=True)
    code = serializers.CharField()
    detail = serializers.CharField()


class ProblemSerializer(serializers.Serializer[None]):
    """The error body of every API response with status 400 and above."""

    type = serializers.CharField()
    title = serializers.CharField()
    status = serializers.IntegerField()
    detail = serializers.CharField()
    code = serializers.CharField()
    # A field named errors shadows Serializer.errors only for the type checker:
    # DRF moves declared fields off the class.
    errors = ProblemFieldErrorSerializer(many=True)  # type: ignore[assignment]

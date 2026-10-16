"""OpenAPI generation: every operation documents its error responses with the
shared Problem component, so the generated TypeScript client knows the shape.

Responses declared with extend_schema win; the defaults only fill gaps:
400 for writes, 401 when the view requires login, 403 when it requires login
or writes (CSRF), 404 for paths with parameters, 429 everywhere (throttles).
"""

from typing import Any

from drf_spectacular import openapi
from drf_spectacular.authentication import SessionScheme
from rest_framework.permissions import AllowAny

from .errors import PROBLEM_CONTENT_TYPE, ProblemSerializer

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AutoSchema(openapi.AutoSchema):
    def _requires_login(self) -> bool:
        permissions = self.view.get_permissions()
        return not all(isinstance(permission, AllowAny) for permission in permissions)

    def _default_error_codes(self) -> list[str]:
        codes = []
        writes = self.method in WRITE_METHODS
        login = self._requires_login()
        if writes:
            codes.append("400")
        if login:
            codes.append("401")
        if login or writes:
            codes.append("403")
        if "{" in self.path:
            codes.append("404")
        codes.append("429")
        return codes

    def _get_response_bodies(self, direction: Any = "response") -> dict[str, Any]:
        responses: dict[str, Any] = super()._get_response_bodies(direction)
        if direction != "response":
            return responses
        for code in self._default_error_codes():
            if code not in responses:
                responses[code] = self._get_response_for_code(  # type: ignore[no-untyped-call]
                    ProblemSerializer, code, [PROBLEM_CONTENT_TYPE], direction
                )
        return responses


class SessionAuthenticationScheme(SessionScheme):  # type: ignore[no-untyped-call]
    """Documents cultures.core.authentication.SessionAuthentication as the cookie scheme."""

    target_class = "cultures.core.authentication.SessionAuthentication"

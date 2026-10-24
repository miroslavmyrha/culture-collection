from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.csp import CSP


class PermissionsPolicyMiddleware:
    """Sends settings.PERMISSIONS_POLICY (Django has no setting for this header)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.policy: str = settings.PERMISSIONS_POLICY

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if self.policy:
            response.headers.setdefault("Permissions-Policy", self.policy)
        return response


class AdminContentSecurityPolicyMiddleware:
    """Gives the admin's pages settings.ADMIN_CSP instead of the API's SECURE_CSP.

    The API's policy allows nothing to load (default-src 'none'), so the admin's own styles and
    scripts were blocked. It sits after ContentSecurityPolicyMiddleware in MIDDLEWARE, so it sees
    the response first and sets the policy that middleware then writes, with its nonce.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.prefix = "/" + settings.ADMIN_PATH.lstrip("/")
        self.policy: dict[str, list[CSP]] = settings.ADMIN_CSP

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if request.path.startswith(self.prefix) and not hasattr(response, "_csp_config"):
            # The attribute Django's csp_override sets, read by its CSP middleware.
            response._csp_config = self.policy  # type: ignore[attr-defined]
        return response

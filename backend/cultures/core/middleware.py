from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse


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

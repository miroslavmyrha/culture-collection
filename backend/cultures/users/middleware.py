from collections.abc import Callable

from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse

from .signin import is_verified


class SecondFactorMiddleware:
    """Ends a signed-in session that has no second factor (ADR 0009, #176).

    cultures.users.signin marks a session when a second factor signs it in. A session signed
    in any other way, one from before #176 included, is signed out here before any view runs,
    in the API and in the admin alike. Right after AuthenticationMiddleware.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if getattr(request.user, "is_authenticated", False) and not is_verified(request):
            logout(request)
        return self.get_response(request)

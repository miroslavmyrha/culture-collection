from django.contrib.auth import authenticate, logout
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import Throttled
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from cultures.core.errors import PROBLEM_CONTENT_TYPE as PROBLEM
from cultures.core.errors import ProblemSerializer
from cultures.core.exceptions import DomainError
from cultures.core.security import enforce_csrf
from cultures.core.throttling import ClientIdentMixin
from cultures.users import factors, signin
from cultures.users.auth import current_user
from cultures.users.login_limits import Attempt, Surface
from cultures.users.models import User

from .serializers import LoginInputSerializer, LoginStepOutputSerializer, MeOutputSerializer


class InvalidCredentials(DomainError):
    status_code = 400
    default_code = "invalid_credentials"
    default_detail = "Invalid username or password."


class LoginThrottle(ClientIdentMixin, SimpleRateThrottle):
    """Rate "login" per client IP (IPv6 per /64), also for anonymous clients.

    Not a ScopedRateThrottle: that one reads the scope from the view's
    throttle_scope and allows every request when it is missing, so nothing is limited.
    """

    scope = "login"

    def get_cache_key(self, request: Request, view: object) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


@extend_schema(responses={204: None})
@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf(request: Request) -> Response:
    """Sets the CSRF cookie; the SPA calls this once before the first write."""
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    request=LoginInputSerializer,
    responses={
        200: LoginStepOutputSerializer,
        (400, PROBLEM): OpenApiResponse(ProblemSerializer, "Invalid input or credentials"),
        (403, PROBLEM): OpenApiResponse(ProblemSerializer, "Missing or invalid CSRF token"),
        (429, PROBLEM): OpenApiResponse(
            ProblemSerializer, "Too many attempts (address, account or both), see Retry-After"
        ),
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login_view(request: Request) -> Response:
    """The password step. It signs nobody in (#176): the answer names the next step, a second
    factor (with the methods this account has) or the enrolment of the first one."""
    enforce_csrf(request)  # anonymous write: DRF would not check CSRF here (login CSRF)
    data = LoginInputSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    attempt = Attempt.of(request, data.validated_data["username"], Surface.API)
    refusal = attempt.refusal()
    if refusal is not None:
        raise Throttled(wait=refusal.wait_seconds(timezone.now()))
    user = authenticate(request, **data.validated_data)
    if not isinstance(user, User):
        attempt.failed()
        raise InvalidCredentials
    signin.begin(request._request, user, data.validated_data["username"], Surface.API)
    found = factors.methods(user)
    has_factor = factors.has_second_factor(user)
    return Response({"step": "second_factor" if has_factor else "enrol", "methods": found})


@extend_schema(request=None, responses={204: None})
@api_view(["POST"])
def logout_view(request: Request) -> Response:
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(responses={200: MeOutputSerializer})
@api_view(["GET"])
def me(request: Request) -> Response:
    """The signed-in user; 401 when nobody is signed in."""
    return Response(MeOutputSerializer(current_user(request)).data)

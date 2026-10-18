"""The project's admin site: the API's login limits, and the own-password form through a service.

Django's AdminSite.login checks a password with no limit, a second way to guess
passwords next to the API login. Here a POST to it passes the same checks as
the API login (cultures.users.api.views.login_view), in the same order:
1. the per-IP throttle LoginThrottle, with the same cache key, so the API and
   the admin login share one budget per client;
2. the failure counters of cultures.users.login_limits, shared with the API:
   the pair back-off, the address budget, and the account under attack, where
   only a browser with the account's known-device cookie may try;
3. Django's login form. A failed attempt (the form again) counts, a
   successful one (the redirect) clears its pair and sets the cookie.
Refusals are a 429 problem with Retry-After, the same as the API's.

The site's own password change view ("Change password" in the header) saves
through user_set_password, like UserAdmin's form for other users.
"""

from http import HTTPStatus
from math import ceil
from typing import Any

from django.contrib import admin
from django.contrib.admin.forms import AdminPasswordChangeForm
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.template.response import TemplateResponse
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.views import APIView

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.core.errors import PROBLEM_CONTENT_TYPE, problem

from . import services
from .api.views import LoginThrottle
from .login_limits import Attempt, Surface
from .models import User

TOO_MANY = "Too many login attempts. Try again later."


def staff_actor(request: HttpRequest) -> User | None:
    """The signed-in user as the audit actor of an admin write."""
    return request.user if isinstance(request.user, User) else None


class OwnPasswordChangeForm(AdminPasswordChangeForm):
    def save(self, commit: bool = True) -> User:
        if not commit:
            raise ValueError("a password is only saved through user_set_password")
        password: str = self.cleaned_data["new_password1"]
        # PasswordChangeView then updates the session hash from form.user: the saved one.
        saved = services.user_set_password(user=self.user, raw_password=password)
        self.user = saved
        return saved


def _too_many(wait: float) -> JsonResponse:
    response = JsonResponse(
        problem(429, "throttled", TOO_MANY), status=429, content_type=PROBLEM_CONTENT_TYPE
    )
    response["Retry-After"] = str(ceil(wait))
    return response


class AdminSite(admin.AdminSite):
    password_change_form = OwnPasswordChangeForm

    def login(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        if request.method != "POST":
            return super().login(request, extra_context)
        throttle = LoginThrottle()
        if not throttle.allow_request(Request(request), APIView()):  # the key ignores the view
            return _too_many(throttle.wait() or 0)
        username = request.POST.get("username", "")
        attempt = Attempt.of(request, username, Surface.ADMIN)
        refusal = attempt.refusal()
        if refusal is not None:
            return _too_many(refusal.wait_seconds(timezone.now()))
        response = super().login(request, extra_context)
        if response.status_code == HTTPStatus.FOUND and isinstance(request.user, User):
            attempt.succeeded(request.user, response)  # LoginView redirects after a valid login
        elif response.status_code == HTTPStatus.OK and username:  # the form again: refused
            attempt.failed()
        return response

    def password_change(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> TemplateResponse:
        with audit_context(channel=Channel.WEB, actor=staff_actor(request)):
            return super().password_change(request, extra_context)

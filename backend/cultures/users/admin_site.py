"""The project's admin site: the app's sign-in, and the own-password form through a service.

Django's AdminSite.login checks a password alone. Since #176 every sign-in needs a second
factor (ADR 0009), so the admin has no login form of its own: a visitor who is not signed in
as staff is sent to the app's sign-in (/login), the same two steps with the same login limits,
and opens the admin again once signed in. A POST with a password to the old form gets the same
redirect and is never checked, so the admin is no way to guess passwords either. A signed-in
session without a second factor never reaches this view: SecondFactorMiddleware ends it.

The site's own password change view ("Change password" in the header) saves
through user_set_password, like UserAdmin's form for other users.
"""

from typing import Any

from django.contrib import admin
from django.contrib.admin.forms import AdminPasswordChangeForm
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse

from cultures.audit.context import audit_context
from cultures.audit.models import Channel

from . import services
from .models import User

# The app's sign-in page (the frontend route): the password step, then the second factor.
APP_SIGN_IN = "/login"


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


class AdminSite(admin.AdminSite):
    password_change_form = OwnPasswordChangeForm

    def login(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        if isinstance(request.user, User) and request.user.is_active and request.user.is_staff:
            return super().login(request, extra_context)  # Django sends them to the index
        return HttpResponseRedirect(APP_SIGN_IN)

    def password_change(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> TemplateResponse:
        with audit_context(channel=Channel.WEB, actor=staff_actor(request)):
            return super().password_change(request, extra_context)

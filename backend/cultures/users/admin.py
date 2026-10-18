"""Staff manage users here, and every save goes through cultures.users.services.

So admin writes are audited like every other write: one AuditEvent per change,
channel "web", the staff user as the actor, and the row trigger's RowChange
rows carry the same actor and request id. Django's stock UserAdmin saves the
model directly and lets staff delete users; this one does neither.
- Profile fields go through user_update (event user_changed).
- Active, staff and superuser status go through their own services and need a
  reason, typed into the change form next to them. The last active manager of
  a lab cannot be deactivated: the form says which lab, and the service
  refuses again under the locks.
- Passwords (the "Reset password" form) go through user_set_password.
- "Failed logins" shows the account's login counter, and "Clear login limits"
  (with a reason) deletes the account's counters through user_login_limits_clear.
- Users are deactivated, never deleted: audit rows point at them.
- Groups and per-user Django permissions are not offered: the app's rights
  come from lab roles (ADR 0006), and nothing would audit those tables.
"""

from typing import TYPE_CHECKING, Any

from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import forms as auth_forms
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.labs.services import labs_left_without_manager

from . import login_limits, services
from .admin_site import staff_actor
from .models import User

# django-stubs makes these generic for mypy only; at run time Django's classes take no
# type arguments (Django 6.1.2) and the project does not install django_stubs_ext.
if TYPE_CHECKING:
    UserAdminBase = auth_admin.UserAdmin[User]
    UserChangeFormBase = auth_forms.UserChangeForm[User]
    PasswordFormBase = auth_forms.AdminPasswordChangeForm[User]
else:
    UserAdminBase = auth_admin.UserAdmin
    UserChangeFormBase = auth_forms.UserChangeForm
    PasswordFormBase = auth_forms.AdminPasswordChangeForm

# Each one is its own service and event type, and needs a reason.
PRIVILEGE_FIELDS = ("is_active", "is_staff", "is_superuser")
REASON_REQUIRED = (
    "A reason is required when active, staff or superuser status changes"
    " or the login limits are cleared."
)
LAST_MANAGER = "This user is the last active manager of {lab}. Make another member a manager first."


class UserChangeForm(UserChangeFormBase):
    clear_login_limits = forms.BooleanField(
        required=False,
        label="Clear login limits",
        help_text=(
            "Ends the wait after failed logins for this account, from every address."
            " Needs a reason."
        ),
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=(
            "Why active, staff or superuser status changes, or why the login limits are"
            " cleared. Stored in the audit trail."
        ),
    )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        needs_reason = set(PRIVILEGE_FIELDS) & set(self.changed_data) or cleaned.get(
            "clear_login_limits"
        )
        if needs_reason and not cleaned.get("reason", "").strip():
            self.add_error("reason", REASON_REQUIRED)
        if "is_active" in self.changed_data and not cleaned.get("is_active"):
            for lab in labs_left_without_manager(users=[self.instance]):
                self.add_error("is_active", LAST_MANAGER.format(lab=lab))
        return cleaned


class PasswordThroughServiceForm(PasswordFormBase):
    """UserAdmin's password form for another user: saves through user_set_password."""

    def save(self, commit: bool = True) -> User:
        if not commit:
            raise ValueError("a password is only saved through user_set_password")
        usable = self.cleaned_data["set_usable_password"]
        password = self.cleaned_data["password1"] if usable else None
        # The view updates the session hash from form.user, so it must be the saved user.
        saved = services.user_set_password(user=self.user, raw_password=password)
        self.user = saved
        return saved


@admin.register(User)
class UserAdmin(UserAdminBase):
    form = UserChangeForm
    change_password_form = PasswordThroughServiceForm
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        (
            "Status",
            {"fields": (*PRIVILEGE_FIELDS, "login_limit_state", "clear_login_limits", "reason")},
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    readonly_fields = ("last_login", "date_joined", "login_limit_state")
    list_filter = ("is_staff", "is_superuser", "is_active")
    filter_horizontal = ()

    @admin.display(description="Failed logins")
    def login_limit_state(self, obj: User) -> str:
        counter = login_limits.account_counter(obj.username, timezone.now())
        if counter is None:
            return "none in the last window"
        until = f"{counter.window_ends_at:%Y-%m-%d %H:%M} UTC"
        if counter.failures >= settings.LOGIN_ACCOUNT_MAX_FAILURES:
            return (
                f"{counter.failures}: under attack until {until}, only known browsers may sign in"
            )
        return f"{counter.failures} until {until}"

    def has_delete_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
        return False  # deactivate instead: audit events and memberships point at users

    def changeform_view(
        self,
        request: HttpRequest,
        object_id: str | None = None,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        with audit_context(channel=Channel.WEB, actor=staff_actor(request)):
            return super().changeform_view(request, object_id, form_url, extra_context)

    def user_change_password(
        self, request: HttpRequest, id: str, form_url: str = ""
    ) -> HttpResponse:
        with audit_context(channel=Channel.WEB, actor=staff_actor(request)):
            return super().user_change_password(request, id, form_url)

    def save_model(self, request: HttpRequest, obj: User, form: Any, change: bool) -> None:
        if not change:
            self._create(obj, form.cleaned_data)
            return
        # obj holds the form's values; the services lock and read the stored row themselves.
        changed = set(form.changed_data)
        services.user_update(
            user=obj, changes={f: getattr(obj, f) for f in services.PROFILE_FIELDS if f in changed}
        )
        reason: str = form.cleaned_data["reason"]
        if "is_active" in changed:
            if obj.is_active:
                services.user_activate(user=obj, reason=reason)
            else:
                services.user_deactivate(user=obj, reason=reason)
        if "is_staff" in changed:
            services.user_set_staff(user=obj, is_staff=obj.is_staff, reason=reason)
        if "is_superuser" in changed:
            services.user_set_superuser(user=obj, is_superuser=obj.is_superuser, reason=reason)
        if form.cleaned_data.get("clear_login_limits"):
            services.user_login_limits_clear(user=obj, reason=reason)

    def _create(self, obj: User, data: dict[str, Any]) -> None:
        """The add form: a username and a password, or none (set_usable_password off)."""
        password = data["password1"] if data["set_usable_password"] else None
        created = services.user_create(username=obj.username, password=password)
        # The admin goes on with `obj` (log entry, redirect): give it the saved row.
        obj.pk, obj.public_id, obj.password = created.pk, created.public_id, created.password
        obj.date_joined = created.date_joined
        obj._state.adding = False

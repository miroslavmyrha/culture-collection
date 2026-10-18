"""Staff create labs and their first members here; the API only reads labs.

Every save goes through the trusted services (cultures.labs.services), so admin
writes are audited like API writes: one AuditEvent each, channel "web", the
staff user as the actor. The forms refuse what the services would refuse
(an inactive user, a second membership, a lab left without an active manager),
so a staff user sees a form error instead of a server error. Labs are never
deleted.
"""

from typing import TYPE_CHECKING, Any

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.users.models import User

from . import services
from .models import Lab, Membership
from .permissions import Role

# django-stubs makes these generic for mypy only; at run time Django's classes take no
# type arguments (Django 6.1.2) and the project does not install django_stubs_ext.
if TYPE_CHECKING:
    MembershipFormBase = forms.ModelForm[Membership]
    MembershipInlineBase = admin.TabularInline[Membership, Lab]
    LabAdminBase = admin.ModelAdmin[Lab]
else:
    MembershipFormBase = forms.ModelForm
    MembershipInlineBase = admin.TabularInline
    LabAdminBase = admin.ModelAdmin


class MembershipForm(MembershipFormBase):
    class Meta:
        model = Membership
        fields = ("user", "role")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        user = self.fields["user"]
        assert isinstance(user, forms.ModelChoiceField)  # noqa: S101 (a type narrowing, not a check)
        user.queryset = User.objects.filter(is_active=True).order_by("username")
        if self.instance.pk is not None:
            user.disabled = True  # a membership changes its role, never its user
            # A disabled field still cleans its initial value against the queryset:
            # keep the member's own user in it, or a lab with an inactive member cannot be saved.
            user.queryset = User.objects.filter(
                Q(is_active=True) | Q(pk=self.instance.user_id)
            ).order_by("username")


class MembershipFormSet(forms.BaseInlineFormSet):  # type: ignore[type-arg]
    def clean(self) -> None:
        super().clean()
        lab = self.instance
        if (
            lab.pk is None
            or not Membership.objects.filter(
                lab=lab, role=Role.MANAGER, user__is_active=True
            ).exists()
        ):
            return  # a lab without an active manager stays editable, so staff can name one
        kept = [
            form.cleaned_data
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        if not any(_active_manager(data) for data in kept):
            raise ValidationError(services.LastManager.default_detail)


def _active_manager(data: dict[str, Any]) -> bool:
    user = data.get("user")
    return data.get("role") == Role.MANAGER and isinstance(user, User) and user.is_active


class MembershipInline(MembershipInlineBase):
    model = Membership
    form = MembershipForm
    formset = MembershipFormSet
    extra = 0


@admin.register(Lab)
class LabAdmin(LabAdminBase):
    list_display = ("name", "code")
    search_fields = ("name", "code")
    ordering = ("name",)
    fields = ("name", "code")
    inlines = (MembershipInline,)

    def has_delete_permission(self, request: HttpRequest, obj: Lab | None = None) -> bool:
        return False  # memberships and audit events point at labs; they are kept

    def changeform_view(
        self,
        request: HttpRequest,
        object_id: str | None = None,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        actor = request.user if isinstance(request.user, User) else None
        with audit_context(channel=Channel.WEB, actor=actor):
            return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request: HttpRequest, obj: Lab, form: Any, change: bool) -> None:
        if change:
            services.lab_update(lab=obj, name=obj.name, code=obj.code)
            return
        created = services.lab_create(name=obj.name, code=obj.code)
        # The inline formsets were built on `obj`: give it the saved row's identity.
        obj.pk, obj.public_id = created.pk, created.public_id
        obj.created_at, obj.updated_at = created.created_at, created.updated_at
        obj._state.adding = False

    def save_formset(self, request: HttpRequest, form: Any, formset: Any, change: bool) -> None:
        formset.save(commit=False)  # fills new_objects, changed_objects and deleted_objects
        lab: Lab = form.instance
        for membership in formset.new_objects:
            services.membership_create(lab=lab, user=membership.user, role=Role(membership.role))
        # Promotions first: demoting one manager while promoting another must not see a lab
        # without a manager in between (LastManager).
        changes = [m for m, fields in formset.changed_objects if "role" in fields]
        for membership in sorted(changes, key=lambda m: m.role != Role.MANAGER):
            services.membership_set_role(membership=membership, role=Role(membership.role))
        for membership in formset.deleted_objects:
            services.membership_delete(membership=membership)

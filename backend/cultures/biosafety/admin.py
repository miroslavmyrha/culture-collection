"""Staff record a lab's permits here and end them; nothing else changes a permit (ADR 0009).

The add form creates a row through biosafety.services; the issuer follows from
the kind. On a recorded permit every field is read-only except the end date
and its reason, and saving with an end date ends it through the service.
Permits are never deleted. Every save runs in an audit context with the
staff user as the actor.
"""

from typing import TYPE_CHECKING, Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest, HttpResponse

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.users.models import User

from . import services
from .models import ISSUER_OF, AuthorisationKind, LabAuthorisation

if TYPE_CHECKING:
    AuthorisationFormBase = forms.ModelForm[LabAuthorisation]
    AuthorisationAdminBase = admin.ModelAdmin[LabAuthorisation]
else:
    AuthorisationFormBase = forms.ModelForm
    AuthorisationAdminBase = admin.ModelAdmin

REASON_HELP = (
    "Why the permit ended, for example 'revoked by decision 2026-114'. Stored for good:"
    " name no person."
)


class AuthorisationForm(AuthorisationFormBase):
    class Meta:
        model = LabAuthorisation
        fields = (
            "lab",
            "kind",
            "permit_reference",
            "valid_from",
            "expires_on",
            "ended_on",
            "end_reason",
        )
        help_texts = {
            "expires_on": "The last day of validity as the permit states it. Empty: none stated.",
            "ended_on": "The day the permit stopped being valid before its expiry.",
            "end_reason": REASON_HELP,
        }

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if self.instance.pk is None:
            kind = data.get("kind")
            if kind in ISSUER_OF:
                self.instance.issuer = ISSUER_OF[AuthorisationKind(kind)]
            return data
        ended_on, reason = data.get("ended_on"), (data.get("end_reason") or "").strip()
        if ended_on and not reason:
            self.add_error("end_reason", "Say why the permit ended.")
        if reason and not ended_on:
            self.add_error("ended_on", "Enter the day the permit ended.")
        return data


@admin.register(LabAuthorisation)
class LabAuthorisationAdmin(AuthorisationAdminBase):
    form = AuthorisationForm
    list_display = (
        "lab",
        "kind",
        "issuer",
        "permit_reference",
        "valid_from",
        "expires_on",
        "ended_on",
    )
    list_filter = ("kind", "issuer")
    search_fields = ("permit_reference", "lab__name", "lab__code")
    ordering = ("lab__name", "kind", "-valid_from")

    def get_fields(
        self, request: HttpRequest, obj: LabAuthorisation | None = None
    ) -> tuple[str, ...]:
        if obj is None:
            return ("lab", "kind", "permit_reference", "valid_from", "expires_on")
        return (
            "lab",
            "kind",
            "issuer",
            "permit_reference",
            "valid_from",
            "expires_on",
            "ended_on",
            "end_reason",
        )

    def get_readonly_fields(
        self, request: HttpRequest, obj: LabAuthorisation | None = None
    ) -> list[str]:
        if obj is None:
            return []
        fixed = ["lab", "kind", "issuer", "permit_reference", "valid_from", "expires_on"]
        return [*fixed, "ended_on", "end_reason"] if obj.ended_on is not None else fixed

    def has_delete_permission(
        self, request: HttpRequest, obj: LabAuthorisation | None = None
    ) -> bool:
        return False  # a permit that ends gets an end date (ADR 0009)

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

    def save_model(
        self, request: HttpRequest, obj: LabAuthorisation, form: Any, change: bool
    ) -> None:
        data = form.cleaned_data
        if not change:
            created = services.authorisation_create(
                lab=data["lab"],
                kind=AuthorisationKind(data["kind"]),
                permit_reference=data["permit_reference"],
                valid_from=data["valid_from"],
                expires_on=data.get("expires_on"),
            )
            obj.pk, obj.public_id = created.pk, created.public_id
            return
        if data.get("ended_on") and "ended_on" in form.changed_data:
            services.authorisation_end(
                authorisation=obj, ended_on=data["ended_on"], reason=data["end_reason"]
            )

"""Staff manage the global box types here; labs pick one when they add a box.

Every save goes through cultures.storage.services inside an audit context with
the staff user as the actor, so admin writes are audited like every other
write. A type keeps its size once created (boxes copied it): rows and columns
are read-only on an existing type. Types are never deleted. Storage units are
managed by the labs themselves, in the app, and have no admin page.
"""

from typing import TYPE_CHECKING, Any

from django.contrib import admin
from django.http import HttpRequest, HttpResponse

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.users.models import User

from . import services
from .models import BoxType

if TYPE_CHECKING:
    BoxTypeAdminBase = admin.ModelAdmin[BoxType]
else:
    BoxTypeAdminBase = admin.ModelAdmin


@admin.register(BoxType)
class BoxTypeAdmin(BoxTypeAdminBase):
    fields = ("name", "rows", "cols")
    list_display = ("name", "rows", "cols")
    search_fields = ("name",)
    ordering = ("name",)

    def get_readonly_fields(
        self, request: HttpRequest, obj: BoxType | None = None
    ) -> tuple[str, ...]:
        return ("rows", "cols") if obj is not None else ()

    def has_delete_permission(self, request: HttpRequest, obj: BoxType | None = None) -> bool:
        return False  # boxes point at their type

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

    def save_model(self, request: HttpRequest, obj: BoxType, form: Any, change: bool) -> None:
        data = form.cleaned_data
        if change:
            services.box_type_rename(box_type=obj, name=data["name"])
            return
        created = services.box_type_create(name=data["name"], rows=data["rows"], cols=data["cols"])
        obj.pk, obj.public_id = created.pk, created.public_id
        obj.created_at, obj.updated_at = created.created_at, created.updated_at
        obj._state.adding = False

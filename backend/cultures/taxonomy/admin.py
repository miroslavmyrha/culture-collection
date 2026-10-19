"""Staff manage the global taxonomy here; labs only read it (ADR 0008, D4).

Every save goes through cultures.taxonomy.services inside an audit context with
the staff user as the actor, so admin writes are audited like every other
write. The form runs the same cross-row rules first (check_taxon), so a
broken rule is a form error, not a server error. Taxa are never deleted:
strains point at them. External ids are added and removed in the inline.
"""

from typing import TYPE_CHECKING, Any

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.core.exceptions import DomainError
from cultures.users.models import User

from . import services
from .models import IdentifierSystem, Rank, Taxon, TaxonIdentifier, TaxonStatus

if TYPE_CHECKING:
    TaxonFormBase = forms.ModelForm[Taxon]
    IdentifierInlineBase = admin.TabularInline[TaxonIdentifier, Taxon]
    TaxonAdminBase = admin.ModelAdmin[Taxon]
else:
    TaxonFormBase = forms.ModelForm
    IdentifierInlineBase = admin.TabularInline
    TaxonAdminBase = admin.ModelAdmin


def fields_of(data: dict[str, Any]) -> services.TaxonFields:
    return services.TaxonFields(
        name=services.normalised(data.get("name") or ""),
        authority=services.normalised(data.get("authority") or ""),
        rank=Rank(data["rank"]),
        parent=data.get("parent"),
        accepted=data.get("accepted"),
    )


class TaxonForm(TaxonFormBase):
    class Meta:
        model = Taxon
        fields = ("name", "authority", "rank", "parent", "accepted")
        help_texts = {
            "authority": "As published, for example (Ehrenberg 1835) Cohn 1872.",
            "parent": "The accepted taxon one rank or more above. Empty for a synonym.",
            "accepted": "Set only for a synonym: the accepted name it stands for.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        accepted_only = Taxon.objects.filter(status=TaxonStatus.ACCEPTED).order_by("name")
        for name in ("parent", "accepted"):
            field = self.fields[name]
            assert isinstance(field, forms.ModelChoiceField)  # noqa: S101 (a type narrowing)
            field.queryset = accepted_only

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if self.errors or "rank" not in data:
            return data
        # The status follows from `accepted`, so the model's own checks see the right values.
        self.instance.status = TaxonStatus.SYNONYM if data.get("accepted") else TaxonStatus.ACCEPTED
        try:
            services.check_taxon(fields_of(data), taxon=self.instance if self.instance.pk else None)
        except DomainError as error:
            raise ValidationError({error.attr or "__all__": error.detail}) from error
        return data


class IdentifierInline(IdentifierInlineBase):
    model = TaxonIdentifier
    fields = ("system", "value")
    extra = 0


@admin.register(Taxon)
class TaxonAdmin(TaxonAdminBase):
    form = TaxonForm
    list_display = ("name", "authority", "rank", "status")
    list_filter = ("rank", "status")
    search_fields = ("name", "authority")
    ordering = ("name",)
    inlines = (IdentifierInline,)
    autocomplete_fields = ()

    def has_delete_permission(self, request: HttpRequest, obj: Taxon | None = None) -> bool:
        return False  # strains and identifications point at taxa: a wrong name becomes a synonym

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

    def save_model(self, request: HttpRequest, obj: Taxon, form: Any, change: bool) -> None:
        fields = fields_of(form.cleaned_data)
        if change:
            services.taxon_update(taxon=obj, fields=fields)
            return
        created = services.taxon_create(fields=fields)
        # The inline formsets were built on `obj`: give it the saved row's identity.
        obj.pk, obj.public_id = created.pk, created.public_id
        obj.created_at, obj.updated_at = created.created_at, created.updated_at
        obj._state.adding = False

    def save_formset(self, request: HttpRequest, form: Any, formset: Any, change: bool) -> None:
        formset.save(commit=False)  # fills new_objects, changed_objects and deleted_objects
        taxon: Taxon = form.instance
        # Removals first: replacing an id of a system removes the old one before adding.
        for identifier in formset.deleted_objects:
            services.taxon_identifier_remove(identifier=identifier)
        for identifier, _ in formset.changed_objects:
            # An id is a fact about a name, not a field to edit: a change is a removal and an add.
            old = TaxonIdentifier.objects.get(pk=identifier.pk)
            services.taxon_identifier_remove(identifier=old)
            services.taxon_identifier_add(
                taxon=taxon, system=IdentifierSystem(identifier.system), value=identifier.value
            )
        for identifier in formset.new_objects:
            services.taxon_identifier_add(
                taxon=taxon, system=IdentifierSystem(identifier.system), value=identifier.value
            )

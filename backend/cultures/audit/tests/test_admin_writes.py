"""Every admin of a row-audited model writes through services, and deletes only through them.

Django's ModelAdmin saves with obj.save() and deletes with obj.delete() or
queryset.delete(), outside audited_atomic(): the row trigger then records the
change with no actor and no request id, and no event explains it. The walk
covers every ModelAdmin on the project's admin site whose model, or whose
inline's model, is in ROW_AUDITED_TABLES:
- save_model is the admin's own, not Django's;
- save_formset is its own when an inline edits a row-audited model;
- it allows no delete (has_delete_permission False for a superuser), or both
  delete_model and delete_queryset are its own.
Whether an override really calls a service is for the admin's own tests
(users/tests/test_admin.py, labs/tests/test_admin.py): this checks that no
admin falls back to Django's writes.
"""

from collections.abc import Mapping
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.admin import ModelAdmin
from django.contrib.auth.models import Group
from django.db.models import Model
from django.http import HttpRequest
from django.test import RequestFactory

from cultures.audit.registry import ROW_AUDITED_TABLES
from cultures.labs.admin import LabAdmin
from cultures.labs.models import Lab
from cultures.users.admin import UserAdmin
from cultures.users.models import User

pytestmark = pytest.mark.django_db


def audited(model: type[Model]) -> bool:
    return model._meta.db_table in ROW_AUDITED_TABLES


def superuser_request() -> HttpRequest:
    request = RequestFactory().get("/")
    request.user = User(username="root", is_staff=True, is_superuser=True, is_active=True)
    return request


def default(model_admin: ModelAdmin[Any], name: str) -> bool:
    """Resolved through the MRO: an override from a mixin counts as the admin's own."""
    return getattr(type(model_admin), name) is getattr(ModelAdmin, name)


def admin_write_violations(
    registry: Mapping[type[Model], ModelAdmin[Any]],
) -> tuple[set[str], list[str]]:
    """(the tables checked, what is wrong), so a caller can assert the walk found something."""
    checked: set[str] = set()
    wrong: list[str] = []
    request = superuser_request()
    for model, model_admin in registry.items():
        inlines = [i for i in model_admin.inlines if audited(i.model)]
        if not audited(model) and not inlines:
            continue
        table = model._meta.db_table
        checked.add(table)
        if audited(model) and default(model_admin, "save_model"):
            wrong.append(f"{table}: save_model is Django's")
        if inlines and default(model_admin, "save_formset"):
            wrong.append(f"{table}: save_formset is Django's, with an audited inline")
        deletes = model_admin.has_delete_permission(request)
        if deletes and (
            default(model_admin, "delete_model") or default(model_admin, "delete_queryset")
        ):
            wrong.append(f"{table}: deletes with Django's delete_model or delete_queryset")
    return checked, wrong


def test_every_admin_of_an_audited_model_writes_through_services() -> None:
    checked, wrong = admin_write_violations(admin.site._registry)
    assert {"users_user", "labs_lab"} <= checked  # an empty walk must not pass
    assert wrong == []


# The invariant itself: each fault it exists to catch makes it fail.


def test_django_s_own_user_admin_is_found() -> None:
    _, wrong = admin_write_violations({User: ModelAdmin(User, admin.site)})
    assert wrong == [
        "users_user: save_model is Django's",
        "users_user: deletes with Django's delete_model or delete_queryset",
    ]


def test_an_admin_that_allows_deletes_without_a_service_is_found() -> None:
    class Deleting(UserAdmin):
        def has_delete_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
            return True

    _, wrong = admin_write_violations({User: Deleting(User, admin.site)})
    assert wrong == ["users_user: deletes with Django's delete_model or delete_queryset"]


def test_an_admin_with_an_audited_inline_and_django_s_save_formset_is_found() -> None:
    class Inlined(LabAdmin):
        save_formset = ModelAdmin.save_formset

    _, wrong = admin_write_violations({Lab: Inlined(Lab, admin.site)})
    assert wrong == ["labs_lab: save_formset is Django's, with an audited inline"]


def test_an_admin_of_a_model_nobody_audits_is_not_checked() -> None:
    checked, wrong = admin_write_violations({Group: ModelAdmin(Group, admin.site)})
    assert (checked, wrong) == (set(), [])

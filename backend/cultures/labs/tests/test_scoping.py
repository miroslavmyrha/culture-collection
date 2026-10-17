"""Invariant: every model with a foreign key to Lab is lab scoped.

"Lab scoped" means its default manager returns a LabScopedQuerySet, whose
for_access(access, perm) is the one filter by the user's labs. The walk goes
over the app registry, so a model added later without the scoped queryset
fails here, and the walk must find something, so a broken walk cannot pass.
"""

from collections.abc import Iterable

import pytest
from django.apps import apps
from django.db import models
from django.test.utils import isolate_apps

from cultures.audit.models import AuditEvent
from cultures.labs.models import Lab, Membership
from cultures.labs.querysets import LabScopedQuerySet


def lab_owned(model_classes: Iterable[type[models.Model]]) -> list[type[models.Model]]:
    return [
        model
        for model in model_classes
        if any(
            isinstance(field, models.ForeignKey) and field.related_model is Lab
            for field in model._meta.get_fields()
        )
    ]


def unscoped(model_classes: Iterable[type[models.Model]]) -> list[str]:
    return [
        model._meta.label
        for model in lab_owned(model_classes)
        if not isinstance(model._default_manager.all(), LabScopedQuerySet)
    ]


def test_every_model_with_a_lab_is_lab_scoped() -> None:
    found = lab_owned(apps.get_models())
    assert {Membership, AuditEvent} <= set(found)  # the walk sees the models it must
    assert unscoped(apps.get_models()) == []


# The invariant itself: a lab-owned model with a plain manager is found.


@isolate_apps("cultures.labs")
def test_a_lab_owned_model_with_a_plain_manager_is_found() -> None:
    class Sample(models.Model):  # noqa: DJ008 (a probe, never shown)
        lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")

        class Meta:
            app_label = "labs"

    class Box(models.Model):  # noqa: DJ008 (a probe, never shown)
        lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")

        objects = LabScopedQuerySet["Box"].as_manager()

        class Meta:
            app_label = "labs"

    assert lab_owned([Sample, Box]) == [Sample, Box]
    assert unscoped([Sample, Box]) == ["labs.Sample"]


@pytest.mark.parametrize("model", [Lab])
def test_a_model_without_a_lab_foreign_key_is_not_walked(model: type[models.Model]) -> None:
    assert lab_owned([model]) == []

"""System checks that keep conventions true as the project grows."""

from collections.abc import Iterable
from typing import Any

from django.apps import apps
from django.core.checks import CheckMessage, Error, register
from django.db import models


def _has_unique_public_id(model: type[models.Model]) -> bool:
    field = model._meta.get_field("public_id")
    if getattr(field, "unique", False):
        return True
    return any(
        isinstance(constraint, models.UniqueConstraint)
        and tuple(constraint.fields) == ("public_id",)
        and constraint.condition is None
        for constraint in model._meta.constraints
    )


@register()
def public_id_is_unique(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    """Every concrete model with public_id keeps it unique (a Meta override can drop it)."""
    return public_id_errors(apps.get_models())


def public_id_errors(model_classes: Iterable[type[models.Model]]) -> list[CheckMessage]:
    errors: list[CheckMessage] = []
    for model in model_classes:
        if model._meta.abstract or not any(f.name == "public_id" for f in model._meta.fields):
            continue
        if not _has_unique_public_id(model):
            errors.append(
                Error(
                    f"{model._meta.label}.public_id is not unique.",
                    hint="Inherit the base Meta: class Meta(PublicModel.Meta).",
                    obj=model,
                    id="core.E001",
                )
            )
    return errors

"""Querysets that scope rows by lab. Imports no models, so any app's models can use them.

Every model with a foreign key to Lab uses a LabScopedQuerySet as its default
manager (tests/test_scoping.py walks the app registry and fails otherwise).
The scope is the set of lab ids from the access object, so a lab the user is
not a member of, or a lab where the role lacks the permission, never matches.
"""

from typing import TYPE_CHECKING, Self

from django.db import models

if TYPE_CHECKING:
    from .access import Access
    from .permissions import Perm


class LabScopedQuerySet[T: models.Model](models.QuerySet[T]):
    """Rows of a model with a `lab` foreign key."""

    lab_field = "lab"

    def for_access(self, access: "Access", perm: "Perm") -> Self:
        return self.filter(**{f"{self.lab_field}__in": access.labs_with(perm)})


class LabQuerySet[T: models.Model](models.QuerySet[T]):
    def for_access(self, access: "Access", perm: "Perm") -> Self:
        return self.filter(pk__in=access.labs_with(perm))

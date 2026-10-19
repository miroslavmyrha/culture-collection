"""Reads of storage. Every one takes the access object, so the lab scope is in the signature."""

from django.db.models import F, QuerySet

from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm

from .models import BoxType, StorageUnit


def unit_tree(*, access: Access, lab: Lab) -> QuerySet[StorageUnit]:
    """Every unit of one lab the user may view, retired ones included, in tree order: each
    unit right after the one holding it, siblings by id. With the parent's public id, the box
    type and the facts of the whole path, in one query."""
    return (
        StorageUnit.objects.for_access(access, Perm.VIEW_STORAGE)
        .filter(lab=lab)
        .select_related("box_type")
        .annotate(parent_public_id=F("parent__public_id"))
        .with_path_facts()
        .order_by("path")
    )


def unit_path(unit: StorageUnit) -> list[StorageUnit]:
    """The units from the root down to the unit's parent: its breadcrumbs. One query."""
    above = {u.pk: u for u in StorageUnit.objects.filter(pk__in=unit.path[:-1])}
    return [above[pk] for pk in unit.path[:-1]]


def unit_children(unit: StorageUnit) -> QuerySet[StorageUnit]:
    """What the unit holds, by slot (units without one last), then name."""
    return (
        StorageUnit.objects.filter(parent=unit)
        .select_related("box_type")
        .order_by(F("slot").asc(nulls_last=True), "name", "pk")
    )


def units_to_manage(access: Access) -> QuerySet[StorageUnit]:
    """The units the user may put something into or move: any lab where they manage storage.
    The service still checks that a parent is in the unit's own lab."""
    return StorageUnit.objects.for_access(access, Perm.MANAGE_STORAGE)


def box_type_list() -> QuerySet[BoxType]:
    """Box types are global: every signed-in user reads them, by name."""
    return BoxType.objects.order_by("name", "pk")

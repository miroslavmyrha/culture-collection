"""Reads of the lab's list of growth media."""

from django.db.models import F, QuerySet

from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm

from .models import GrowthMedium


def medium_list(*, access: Access, lab: Lab) -> QuerySet[GrowthMedium]:
    """The lab's media, active ones first, by name."""
    return (
        GrowthMedium.objects.for_access(access, Perm.VIEW_STRAINS)
        .filter(lab=lab)
        .order_by(F("retired_at").asc(nulls_first=True), "name", "id")
    )

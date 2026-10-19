from typing import Any

import django_filters
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema, extend_schema_view

from cultures.core.api import AUTHENTICATED, ScopedReadOnlyViewSet
from cultures.taxonomy import selectors
from cultures.taxonomy.models import Taxon

from .serializers import TaxonOutputSerializer


class TaxonFilter(django_filters.FilterSet):  # type: ignore[misc]  # FilterSet is Any: no types
    search = django_filters.CharFilter(method="filter_search", max_length=200)

    class Meta:
        model = Taxon
        fields = ("search",)

    def filter_search(self, queryset: QuerySet[Taxon], name: str, value: str) -> QuerySet[Taxon]:
        return selectors.taxon_search(queryset, text=value)


# The global taxonomy, read only: every signed-in user reads it, staff change it in admin
# (ADR 0008, D4). There is nothing lab-scoped in a taxon, so there is no outsider: the
# contract coverage lists this view in EXEMPT with the tests that call it.
@extend_schema_view(
    list=extend_schema(description="Taxa by name. `search` finds names containing the text."),
)
class TaxonViewSet(ScopedReadOnlyViewSet):
    action_perms = {"list": AUTHENTICATED, "retrieve": AUTHENTICATED}
    serializer_class = TaxonOutputSerializer
    filterset_class = TaxonFilter

    def scoped_queryset(self) -> QuerySet[Any]:
        return selectors.taxon_list()

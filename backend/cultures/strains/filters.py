import django_filters
from django.db.models import QuerySet

from cultures.biosafety.models import RestrictionKind
from cultures.taxonomy.models import Taxon

from . import selectors
from .models import Strain, StrainStatus

RISK_GROUPS = [(1, "1"), (2, "2"), (3, "3"), (4, "4")]


class StrainFilter(django_filters.FilterSet):  # type: ignore[misc]  # FilterSet is Any: no types
    """Applied by DjangoFilterBackend to the viewset's scoped queryset, never to all rows.

    Explicit fields only. An unknown value answers 400, never the whole list. Taxa are global,
    so the taxon filter resolves against every taxon: it cannot reveal another lab's rows,
    because the queryset it narrows is already the lab's.
    """

    taxon = django_filters.ModelChoiceFilter(
        queryset=Taxon.objects.all(), to_field_name="public_id", method="filter_taxon"
    )
    risk_group = django_filters.TypedChoiceFilter(choices=RISK_GROUPS, coerce=int)
    status = django_filters.ChoiceFilter(choices=StrainStatus.choices)
    restriction = django_filters.ChoiceFilter(
        choices=RestrictionKind.choices, method="filter_restriction"
    )
    search = django_filters.CharFilter(method="filter_search", max_length=200)

    class Meta:
        model = Strain
        fields = ("taxon", "risk_group", "status", "restriction", "search")

    def filter_taxon(self, queryset: QuerySet[Strain], name: str, value: Taxon) -> QuerySet[Strain]:
        return selectors.under_taxon(queryset, value)

    def filter_restriction(
        self, queryset: QuerySet[Strain], name: str, value: str
    ) -> QuerySet[Strain]:
        return selectors.with_restriction(queryset, RestrictionKind(value))

    def filter_search(self, queryset: QuerySet[Strain], name: str, value: str) -> QuerySet[Strain]:
        return selectors.matching(queryset, value)

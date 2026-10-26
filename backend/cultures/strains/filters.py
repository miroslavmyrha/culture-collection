import django_filters
from django.db.models import QuerySet
from rest_framework.request import Request

from cultures.biosafety.models import RestrictionKind
from cultures.deposits import selectors as deposits
from cultures.deposits.models import Depositor
from cultures.labs.access import access_of
from cultures.taxonomy.models import Taxon

from . import selectors
from .countries import COUNTRY_CODES
from .models import Strain, StrainStatus

RISK_GROUPS = [(1, "1"), (2, "2"), (3, "3"), (4, "4")]
COUNTRY_CHOICES = [(code, code) for code in sorted(COUNTRY_CODES)]


def lab_depositors(request: Request) -> QuerySet[Depositor]:
    """The depositors the caller may name: this lab's, and none for a role without
    deposits.view. A depositor is a person's contact, so a viewer cannot learn through this
    filter which strains one person gave. Another lab's depositor, an unknown one and a
    forbidden one all answer the same 400."""
    lab = request.parser_context["view"].lab
    return deposits.depositor_list(access=access_of(request), lab=lab)


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
    isolation_source = django_filters.CharFilter(method="filter_isolation_source", max_length=200)
    country = django_filters.ChoiceFilter(choices=COUNTRY_CHOICES, method="filter_country")
    depositor = django_filters.ModelChoiceFilter(
        queryset=lab_depositors, to_field_name="public_id", method="filter_depositor"
    )

    class Meta:
        model = Strain
        fields = (
            "taxon",
            "risk_group",
            "status",
            "restriction",
            "search",
            "isolation_source",
            "country",
            "depositor",
        )

    def filter_taxon(self, queryset: QuerySet[Strain], name: str, value: Taxon) -> QuerySet[Strain]:
        return selectors.under_taxon(queryset, value)

    def filter_restriction(
        self, queryset: QuerySet[Strain], name: str, value: str
    ) -> QuerySet[Strain]:
        return selectors.with_restriction(queryset, RestrictionKind(value))

    def filter_search(self, queryset: QuerySet[Strain], name: str, value: str) -> QuerySet[Strain]:
        return selectors.matching(queryset, value)

    def filter_isolation_source(
        self, queryset: QuerySet[Strain], name: str, value: str
    ) -> QuerySet[Strain]:
        return selectors.with_isolation_source(queryset, value)

    def filter_country(self, queryset: QuerySet[Strain], name: str, value: str) -> QuerySet[Strain]:
        return queryset.filter(country_of_origin=value)

    def filter_depositor(
        self, queryset: QuerySet[Strain], name: str, value: Depositor
    ) -> QuerySet[Strain]:
        return selectors.from_depositor(queryset, value)

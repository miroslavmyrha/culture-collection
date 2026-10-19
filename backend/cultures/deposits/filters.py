import django_filters
from django.db.models import QuerySet

from . import selectors
from .models import Deposit, Depositor, DepositStatus


class DepositFilter(django_filters.FilterSet):  # type: ignore[misc]  # FilterSet is Any: no types
    """Applied to the viewset's scoped queryset only. Explicit fields; an unknown status is 400."""

    status = django_filters.ChoiceFilter(choices=DepositStatus.choices)
    search = django_filters.CharFilter(method="filter_search", max_length=200)

    class Meta:
        model = Deposit
        fields = ("status", "search")

    def filter_search(
        self, queryset: QuerySet[Deposit], name: str, value: str
    ) -> QuerySet[Deposit]:
        return selectors.deposit_matching(queryset, value)


class DepositorFilter(django_filters.FilterSet):  # type: ignore[misc]
    search = django_filters.CharFilter(method="filter_search", max_length=200)

    class Meta:
        model = Depositor
        fields = ("search",)

    def filter_search(
        self, queryset: QuerySet[Depositor], name: str, value: str
    ) -> QuerySet[Depositor]:
        return selectors.depositor_matching(queryset, value)

import django_filters
from django.db.models import QuerySet

from . import selectors
from .models import DistributionRequest, RecipientPermit, Requester, RequestStatus


class RequestFilter(django_filters.FilterSet):  # type: ignore[misc]  # FilterSet is Any: no types
    """Applied to the viewset's scoped queryset only. Explicit fields; an unknown status is 400."""

    status = django_filters.ChoiceFilter(choices=RequestStatus.choices)
    requester = django_filters.UUIDFilter(field_name="requester__public_id")
    search = django_filters.CharFilter(method="filter_search", max_length=200)

    class Meta:
        model = DistributionRequest
        fields = ("status", "requester", "search")

    def filter_search(
        self, queryset: QuerySet[DistributionRequest], name: str, value: str
    ) -> QuerySet[DistributionRequest]:
        return selectors.request_matching(queryset, value)


class RequesterFilter(django_filters.FilterSet):  # type: ignore[misc]
    search = django_filters.CharFilter(method="filter_search", max_length=200)

    class Meta:
        model = Requester
        fields = ("search",)

    def filter_search(
        self, queryset: QuerySet[Requester], name: str, value: str
    ) -> QuerySet[Requester]:
        return selectors.requester_matching(queryset, value)


class PermitFilter(django_filters.FilterSet):  # type: ignore[misc]
    requester = django_filters.UUIDFilter(field_name="requester__public_id")

    class Meta:
        model = RecipientPermit
        fields = ("requester",)

import django_filters

from .models import Batch, Passage, Vial


class PassageFilter(django_filters.FilterSet):  # type: ignore[misc]  # FilterSet is Any: no types
    """Applied to the viewset's scoped queryset, never to all rows. An unknown strain id
    narrows the list to nothing, a malformed one answers 400."""

    strain = django_filters.UUIDFilter(field_name="strain__public_id")

    class Meta:
        model = Passage
        fields = ("strain",)


class BatchFilter(django_filters.FilterSet):  # type: ignore[misc]
    strain = django_filters.UUIDFilter(field_name="strain__public_id")

    class Meta:
        model = Batch
        fields = ("strain",)


class VialFilter(django_filters.FilterSet):  # type: ignore[misc]
    strain = django_filters.UUIDFilter(field_name="batch__strain__public_id")
    batch = django_filters.UUIDFilter(field_name="batch__public_id")

    class Meta:
        model = Vial
        fields = ("strain", "batch")

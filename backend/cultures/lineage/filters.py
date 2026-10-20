import re

import django_filters
from django.db.models import Q, QuerySet

from .models import Batch, BatchCheck, Passage, Vial

# A vial's label as printed: "<accession number> / <batch> / <seq>" ("MYC 42 / 1 / 3"). The
# spaces around the slashes may be missing, as a person types it.
LABEL = re.compile(r"(?P<accession>\S.*?)\s*/\s*(?P<batch>\d{1,9})\s*/\s*(?P<seq>\d{1,9})")


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


class BatchCheckFilter(django_filters.FilterSet):  # type: ignore[misc]
    batch = django_filters.UUIDFilter(field_name="batch__public_id")
    strain = django_filters.UUIDFilter(field_name="batch__strain__public_id")

    class Meta:
        model = BatchCheck
        fields = ("batch", "strain")


class VialFilter(django_filters.FilterSet):  # type: ignore[misc]
    strain = django_filters.UUIDFilter(field_name="batch__strain__public_id")
    batch = django_filters.UUIDFilter(field_name="batch__public_id")
    # What a person types or a scanner sends at the bench (#15): the vial's barcode, exactly,
    # or its label, the accession number without regard to case.
    code = django_filters.CharFilter(method="by_code", max_length=200)

    class Meta:
        model = Vial
        fields = ("strain", "batch", "code")

    def by_code(self, queryset: QuerySet[Vial], name: str, value: str) -> QuerySet[Vial]:
        text = " ".join(value.split())
        match = Q(barcode=text)
        label = LABEL.fullmatch(text)
        if label is not None:
            match |= Q(
                batch__strain__accession_number__iexact=label["accession"],
                batch__number=int(label["batch"]),
                seq=int(label["seq"]),
            )
        return queryset.filter(match)

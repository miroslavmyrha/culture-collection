from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from rest_framework import pagination
from rest_framework.request import Request
from rest_framework.views import APIView

TIE_BREAKERS = {"pk", "-pk", "id", "-id"}


def with_total_ordering(queryset: QuerySet[Any]) -> QuerySet[Any]:
    """Append pk to the ordering so rows with equal sort keys keep a stable order.

    Without it, pages over tied keys (same name, same date) can repeat or skip
    rows. An unordered queryset is refused: the view must choose an order.
    """
    if not queryset.ordered:
        raise ImproperlyConfigured(
            f"Paginated queryset of {queryset.model.__name__} has no ordering: "
            "add .order_by(...) in the selector or Meta.ordering."
        )
    query = queryset.query
    ordering = list(query.order_by or ()) or (
        list(query.get_meta().ordering or ()) if query.default_ordering else []
    )
    if any(str(term) in TIE_BREAKERS for term in ordering):
        return queryset
    return queryset.order_by(*ordering, "pk")


class LimitOffsetPagination(pagination.LimitOffsetPagination):
    max_limit = 200  # ?limit=1000000 gets 200 rows, never the whole table

    def paginate_queryset(
        self, queryset: Any, request: Request, view: APIView | None = None
    ) -> list[Any] | None:
        if isinstance(queryset, QuerySet):
            queryset = with_total_ordering(queryset)
        return super().paginate_queryset(queryset, request, view)

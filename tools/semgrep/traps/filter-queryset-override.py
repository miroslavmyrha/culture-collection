from rest_framework import filters, viewsets


class SampleViewSet(viewsets.ModelViewSet):
    # ruleid: filter-queryset-override
    def filter_queryset(self, queryset):
        return queryset.filter(status=self.request.query_params.get("status"))


class BoxViewSet(viewsets.ModelViewSet):
    # ok: filter-queryset-override
    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        return queryset.filter(archived=False)


class OwnerFilter(filters.BaseFilterBackend):
    # ok: filter-queryset-override
    def filter_queryset(self, request, queryset, view):
        return queryset.filter(owner=request.user)

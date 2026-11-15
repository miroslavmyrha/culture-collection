from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Box, Sample


class SampleViewSet(viewsets.ModelViewSet):
    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        # ruleid: action-bypasses-get-object
        sample = Sample.objects.get(pk=pk)
        sample.discard()
        return Response(status=204)

    @action(methods=["post"], detail=True)
    def move(self, request, pk=None):
        # ruleid: action-bypasses-get-object
        sample = get_object_or_404(Sample, pk=pk)
        # ok: action-bypasses-get-object
        box = self.get_object().box
        # ok: action-bypasses-get-object
        target = Box.objects.get(barcode=request.data["box"])
        return Response({"sample": sample.pk, "from": box.pk, "to": target.pk})

    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        sample = self.get_object()
        # ok: action-bypasses-get-object
        fresh = Sample.objects.get(pk=sample.pk)
        return Response({"sample": fresh.pk})

    @action(detail=False)
    def recent(self, request):
        # ok: action-bypasses-get-object
        return Response(list(self.get_queryset().values_list("pk", flat=True)[:10]))

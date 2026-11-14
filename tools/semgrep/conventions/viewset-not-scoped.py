from rest_framework import generics, viewsets

from proj.core.api import ScopedModelViewSet

from .models import Sample


# ruleid: viewset-not-scoped
class SampleViewSet(viewsets.ModelViewSet):
    queryset = Sample.objects.all()


# ruleid: viewset-not-scoped
class SampleList(generics.ListAPIView):
    queryset = Sample.objects.all()


# ok: viewset-not-scoped
class BoxViewSet(ScopedModelViewSet):
    pass


class LabScoped:
    pass


# ok: viewset-not-scoped
class LabNested(LabScoped, viewsets.ReadOnlyModelViewSet, abstract=True):
    pass

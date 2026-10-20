from rest_framework.routers import SimpleRouter

from .views import BatchCheckViewSet, BatchViewSet, BoxViewSet, PassageViewSet, VialViewSet

# Nested one level under the lab, like strains and storage units; filtered by strain.
router = SimpleRouter()
router.register(
    r"labs/(?P<lab_public_id>[0-9a-f-]+)/passages", PassageViewSet, basename="lab-passage"
)
router.register(r"labs/(?P<lab_public_id>[0-9a-f-]+)/batches", BatchViewSet, basename="lab-batch")
router.register(
    r"labs/(?P<lab_public_id>[0-9a-f-]+)/batch-checks",
    BatchCheckViewSet,
    basename="lab-batch-check",
)
router.register(r"labs/(?P<lab_public_id>[0-9a-f-]+)/vials", VialViewSet, basename="lab-vial")
router.register(r"labs/(?P<lab_public_id>[0-9a-f-]+)/boxes", BoxViewSet, basename="lab-box")
urlpatterns = router.urls

from rest_framework.routers import SimpleRouter

from .views import BatchViewSet, PassageViewSet, VialViewSet

# Nested one level under the lab, like strains and storage units; filtered by strain.
router = SimpleRouter()
router.register(
    r"labs/(?P<lab_public_id>[0-9a-f-]+)/passages", PassageViewSet, basename="lab-passage"
)
router.register(r"labs/(?P<lab_public_id>[0-9a-f-]+)/batches", BatchViewSet, basename="lab-batch")
router.register(r"labs/(?P<lab_public_id>[0-9a-f-]+)/vials", VialViewSet, basename="lab-vial")
urlpatterns = router.urls

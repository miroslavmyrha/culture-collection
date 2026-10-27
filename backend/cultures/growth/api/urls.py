from rest_framework.routers import SimpleRouter

from .views import MediumViewSet

# Nested one level under the lab, like strains and members.
router = SimpleRouter()
router.register(r"labs/(?P<lab_public_id>[0-9a-f-]+)/media", MediumViewSet, basename="lab-medium")
urlpatterns = router.urls

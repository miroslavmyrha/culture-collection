from rest_framework.routers import SimpleRouter

from .views import StrainViewSet

# Nested one level under the lab, like members (api-design: resolve the parent first).
router = SimpleRouter()
router.register(r"labs/(?P<lab_public_id>[0-9a-f-]+)/strains", StrainViewSet, basename="lab-strain")
urlpatterns = router.urls

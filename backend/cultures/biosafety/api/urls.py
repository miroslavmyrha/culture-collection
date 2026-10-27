from rest_framework.routers import SimpleRouter

from .views import PermitViewSet

# Nested one level under the lab, like the members.
router = SimpleRouter()
router.register(r"labs/(?P<lab_public_id>[0-9a-f-]+)/permits", PermitViewSet, basename="lab-permit")
urlpatterns = router.urls

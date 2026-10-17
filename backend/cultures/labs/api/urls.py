from rest_framework.routers import SimpleRouter

from .views import LabViewSet, MemberViewSet

# SimpleRouter: no browsable API root next to the other apps' routes. Members are nested
# one level under their lab (api-design: resolve the parent first, then the child through it).
router = SimpleRouter()
router.register("labs", LabViewSet, basename="lab")
router.register(r"labs/(?P<lab_public_id>[0-9a-f-]+)/members", MemberViewSet, basename="lab-member")
urlpatterns = router.urls

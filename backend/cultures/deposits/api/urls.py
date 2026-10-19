from rest_framework.routers import SimpleRouter

from .views import DepositorViewSet, DepositViewSet, MtaTemplateViewSet

# Nested one level under the lab, like members and strains (api-design: resolve the parent first).
LAB = r"labs/(?P<lab_public_id>[0-9a-f-]+)"
router = SimpleRouter()
router.register(f"{LAB}/depositors", DepositorViewSet, basename="lab-depositor")
router.register(f"{LAB}/mta-templates", MtaTemplateViewSet, basename="lab-mta-template")
router.register(f"{LAB}/deposits", DepositViewSet, basename="lab-deposit")
urlpatterns = router.urls

from rest_framework.routers import SimpleRouter

from .views import (
    DocumentViewSet,
    PermitViewSet,
    RequesterViewSet,
    RequestViewSet,
    ShipmentDocumentViewSet,
)

# Nested one level under the lab, like deposits (api-design: resolve the parent first).
LAB = r"labs/(?P<lab_public_id>[0-9a-f-]+)"
router = SimpleRouter()
router.register(f"{LAB}/requesters", RequesterViewSet, basename="lab-requester")
router.register(f"{LAB}/recipient-permits", PermitViewSet, basename="lab-recipient-permit")
router.register(f"{LAB}/documents", DocumentViewSet, basename="lab-document")
router.register(f"{LAB}/requests", RequestViewSet, basename="lab-request")
router.register(
    f"{LAB}/shipment-documents", ShipmentDocumentViewSet, basename="lab-shipment-document"
)
urlpatterns = router.urls

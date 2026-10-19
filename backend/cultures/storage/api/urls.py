from rest_framework.routers import SimpleRouter

from .views import BoxTypeViewSet, StorageUnitViewSet

# Units nested one level under the lab, like strains; box types are global, like taxa.
router = SimpleRouter()
router.register(
    r"labs/(?P<lab_public_id>[0-9a-f-]+)/storage-units", StorageUnitViewSet, basename="lab-unit"
)
router.register("box-types", BoxTypeViewSet, basename="box-type")
urlpatterns = router.urls

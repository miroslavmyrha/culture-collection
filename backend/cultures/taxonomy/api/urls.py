from rest_framework.routers import SimpleRouter

from .views import TaxonViewSet

router = SimpleRouter()
router.register("taxa", TaxonViewSet, basename="taxon")
urlpatterns = router.urls

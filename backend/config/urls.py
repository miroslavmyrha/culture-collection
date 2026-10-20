from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

# Liveness /healthz and readiness /readyz are served by cultures.core.health.HealthCheckMiddleware.
urlpatterns = [
    path(settings.ADMIN_PATH, admin.site.urls),
    path("api/v1/auth/", include("cultures.users.api.urls")),
    path("api/v1/", include("cultures.labs.api.urls")),
    path("api/v1/", include("cultures.taxonomy.api.urls")),
    path("api/v1/", include("cultures.strains.api.urls")),
    path("api/v1/", include("cultures.deposits.api.urls")),
    path("api/v1/", include("cultures.storage.api.urls")),
    path("api/v1/", include("cultures.lineage.api.urls")),
    path("api/v1/", include("cultures.distribution.api.urls")),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
]

# Errors outside DRF views (unknown URLs, crashes in middleware) use the API's problem shape.
handler400 = "cultures.core.errors.bad_request"
handler403 = "cultures.core.errors.permission_denied"
handler404 = "cultures.core.errors.not_found"
handler500 = "cultures.core.errors.server_error"

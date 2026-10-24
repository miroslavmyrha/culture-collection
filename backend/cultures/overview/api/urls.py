from django.urls import path

from . import views

# The signed-in person's own view across their labs: no lab in the URL, scoped by membership.
urlpatterns = [
    path("me/overview/", views.overview, name="me-overview"),
    path("me/activity/", views.recent_activity, name="me-activity"),
]

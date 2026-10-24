from django.urls import path

from . import views

# The signed-in person's search across their labs: no lab in the URL, scoped by membership.
urlpatterns = [path("me/search/", views.search, name="me-search")]

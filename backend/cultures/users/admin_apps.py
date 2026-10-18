"""Replaces "django.contrib.admin" in INSTALLED_APPS, so admin.site is our AdminSite.

Its own module: INSTALLED_APPS imports it before the models are ready, and
apps.py may hold only one AppConfig (Django picks the one with default = True,
which this one inherits).
"""

from django.contrib.admin.apps import AdminConfig as DjangoAdminConfig


class AdminConfig(DjangoAdminConfig):
    default_site = "cultures.users.admin_site.AdminSite"

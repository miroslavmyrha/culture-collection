"""Delete login failure counters whose window has ended (cultures.users.login_limits).

    python manage.py prune_login_failures

An ended counter counts nothing: the next failure starts it again at 1. Pruning
only keeps the table small, so a flood of failed logins for made-up names does
not stay in it. Run it hourly as the runtime role (it needs DELETE only on
users_loginfailures). Running it twice in a row deletes nothing the second time.
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from cultures.users import login_limits


class Command(BaseCommand):
    help = "Delete login failure counters whose window has ended."

    def handle(self, *args: Any, **options: Any) -> None:
        deleted = login_limits.prune(timezone.now())
        self.stdout.write(f"deleted {deleted} ended login failure counters")

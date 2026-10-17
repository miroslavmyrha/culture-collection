"""Django's createsuperuser, run in an audit context.

Django's command saves the new user through the user manager's
create_superuser, which here goes through the services (superuser_create):
the user, staff and superuser events are recorded with channel command, actor
kind system and the label "command:createsuperuser". Prompts, options and
DJANGO_SUPERUSER_* variables are Django's, unchanged. This command replaces
Django's because cultures.users comes before django.contrib.auth in
INSTALLED_APPS.
"""

from typing import Any

from django.contrib.auth.management.commands import createsuperuser

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, Channel

LABEL = "command:createsuperuser"
REASON = "created with manage.py createsuperuser"


class Command(createsuperuser.Command):
    def handle(self, *args: Any, **options: Any) -> None:
        with audit_context(
            channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label=LABEL, reason=REASON
        ):
            super().handle(*args, **options)

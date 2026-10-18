"""Django's changepassword, saving through user_set_password.

Same arguments, prompts and password validation as Django's command, but the
new password is saved by the audited service: the event user_password_changed
(channel command, actor kind system, label "command:changepassword") and the
row trigger's marker share one request id. Django's handle() saves the user
itself, so the prompt loop is ours. This command replaces Django's because
cultures.users comes before django.contrib.auth in INSTALLED_APPS.
"""

import getpass
from typing import Any

from django.contrib.auth.management.commands import changepassword
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, Channel
from cultures.users.models import User
from cultures.users.services import user_set_password

LABEL = "command:changepassword"
MAX_TRIES = 3


class Command(changepassword.Command):
    def _get_pass(self, prompt: str = "Password: ") -> str:
        """One hidden prompt; empty input aborts, as in Django's command. Tests replace it."""
        password = getpass.getpass(prompt=prompt)
        if not password:
            raise CommandError("aborted")
        return password

    def handle(self, *args: Any, **options: Any) -> str:
        username = options["username"] or getpass.getuser()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"user '{username}' does not exist") from None
        self.stdout.write(f"Changing password for user '{user}'")
        password = self._ask(user)
        with audit_context(channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label=LABEL):
            user_set_password(user=user, raw_password=password)
        return f"Password changed successfully for user '{user}'"

    def _ask(self, user: User) -> str:
        """A password typed twice that passes the validators, in at most MAX_TRIES rounds."""
        for _ in range(MAX_TRIES):
            first = self._get_pass()
            if first != self._get_pass("Password (again): "):
                self.stdout.write("Passwords do not match. Please try again.")
                continue
            try:
                validate_password(first, user)
            except ValidationError as error:
                self.stderr.write("\n".join(error.messages))
                continue
            return first
        raise CommandError(f"Aborting password change for user '{user}' after {MAX_TRIES} attempts")

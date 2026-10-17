"""The data the Playwright tests use, locally and in CI. Refused unless DEBUG is on.

    E2E_PASSWORD=... python manage.py seed_e2e

Brings the database to this state, whatever it was before:
- E2E_USERNAME (default e2e-user), active, with the password from E2E_PASSWORD
  (or E2E_PASSWORD_FILE);
- e2e-colleague, active, without a usable password and in no lab: the e2e test
  adds it as a member, changes its role and removes it again;
- the lab "E2E lab" (code E2E) with the e2e user as its manager.
A second run changes nothing. Every lab and membership write goes through the
services with their audit events (channel command, actor kind system).
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.env import env_secret, env_str
from cultures.audit.context import audit_context, audited_atomic
from cultures.audit.models import ActorKind, Channel
from cultures.labs import services
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.users.models import User

LAB_NAME, LAB_CODE = "E2E lab", "E2E"
COLLEAGUE = "e2e-colleague"


class Command(BaseCommand):
    help = "Create or reset the e2e users, lab and membership (development and CI only)."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_e2e creates a known password: it runs only with DEBUG on.")
        username = env_str("E2E_USERNAME", "e2e-user")
        password = env_secret("E2E_PASSWORD")
        if not password.strip():
            raise CommandError("E2E_PASSWORD is empty.")
        with audit_context(
            channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label="command:seed_e2e"
        ):
            user = self._user(username, password)
            colleague = self._user(COLLEAGUE, None)
            lab = Lab.objects.filter(code=LAB_CODE).first() or services.lab_create(
                name=LAB_NAME, code=LAB_CODE
            )
            self._role(lab, user, Role.MANAGER)
            for membership in Membership.objects.filter(lab=lab, user=colleague):
                services.membership_delete(membership=membership)
        self.stdout.write(f"{username} manages {lab.name}; {COLLEAGUE} is in no lab")

    def _user(self, username: str, password: str | None) -> User:
        with audited_atomic():  # the row trigger joins these writes to the command's request id
            user = User.objects.filter(username=username).first() or User(username=username)
            changed = user.pk is None or not user.is_active
            user.is_active = True
            if password is None:
                if user.pk is None or user.has_usable_password():
                    user.set_unusable_password()
                    changed = True
            elif not user.check_password(password):
                user.set_password(password)
                changed = True
            if changed:
                user.save()
        return user

    def _role(self, lab: Lab, user: User, role: Role) -> None:
        membership = Membership.objects.filter(lab=lab, user=user).first()
        if membership is None:
            services.membership_create(lab=lab, user=user, role=role)
        else:
            services.membership_set_role(membership=membership, role=role)

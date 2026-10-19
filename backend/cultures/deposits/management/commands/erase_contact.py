"""Erase a depositor's contact on an erasure request (ADR 0005, #37; ADR 0008, D11).

    python manage.py erase_contact <contact public id> --by <staff username> --reason "..."

The name, e-mail and postal address are emptied in place and the contact is
marked erased; the depositor, its deposits and every audit row stay. The staff
member who runs it is the event's actor, so --by must name an active staff
user. The reason says why ("erasure request 2026-120"), never who. A contact
erased already is left as it is, with no second event.
"""

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.deposits import services
from cultures.deposits.models import Contact
from cultures.users.models import User


class Command(BaseCommand):
    help = "Erase a contact's name, e-mail and postal address (an erasure request)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("contact", help="The contact's public id.")
        parser.add_argument("--by", required=True, help="The username of the staff member.")
        parser.add_argument(
            "--reason", required=True, help="Why, in a sentence. Stored for good: name no person."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        staff = User.objects.filter(username=options["by"], is_staff=True, is_active=True).first()
        if staff is None:
            raise CommandError("--by must name an active staff user.")
        public_id = _uuid(options["contact"])
        contact = Contact.objects.filter(public_id=public_id).first() if public_id else None
        if contact is None:
            raise CommandError("No contact has this public id.")
        if contact.erased_at is not None:
            self.stdout.write(f"contact {contact.public_id} was erased already")
            return
        with audit_context(channel=Channel.COMMAND, actor=staff):
            services.contact_erase(contact=contact, reason=options["reason"])
        self.stdout.write(f"contact {contact.public_id} erased")


def _uuid(text: str) -> str | None:
    try:
        return str(UUID(text))
    except ValueError:
        return None

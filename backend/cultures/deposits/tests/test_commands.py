"""erase_contact: staff erase a depositor's contact on request, with a reason."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from cultures.audit.models import AuditEvent, Channel
from cultures.deposits.models import Contact, Depositor
from cultures.labs.tests.conftest import make_user

pytestmark = pytest.mark.django_db


def erase(*args: str) -> str:
    out = StringIO()
    call_command("erase_contact", *args, stdout=out)
    return out.getvalue()


def test_staff_erase_a_contact_and_are_its_actor(depositor: Depositor) -> None:
    staff = make_user("staff", is_staff=True)
    contact = depositor.contact
    output = erase(str(contact.public_id), "--by", "staff", "--reason", "erasure request 2026-120")
    assert output == f"contact {contact.public_id} erased\n"
    erased = Contact.objects.get(pk=contact.pk)
    assert (erased.name, erased.email, erased.postal_address) == ("", "", "")
    event = AuditEvent.objects.get(event_type="contact_erased")
    assert (event.actor, event.channel, event.reason) == (
        staff,
        Channel.COMMAND,
        "erasure request 2026-120",
    )
    assert erase(str(contact.public_id), "--by", "staff", "--reason", "again") == (
        f"contact {contact.public_id} was erased already\n"
    )
    assert AuditEvent.objects.filter(event_type="contact_erased").count() == 1


@pytest.mark.parametrize(
    ("contact", "by", "message"),
    [
        ("own", "member", "--by must name an active staff user."),
        ("own", "nobody", "--by must name an active staff user."),
        ("00000000-0000-4000-8000-000000000999", "staff", "No contact has this public id."),
        ("not-a-uuid", "staff", "No contact has this public id."),
    ],
)
def test_it_refuses_a_non_staff_actor_and_an_unknown_contact(
    depositor: Depositor, contact: str, by: str, message: str
) -> None:
    make_user("staff", is_staff=True)
    make_user("member")
    target = str(depositor.contact.public_id) if contact == "own" else contact
    with pytest.raises(CommandError, match=message):
        erase(target, "--by", by, "--reason", "erasure request")
    assert Contact.objects.get(pk=depositor.contact_id).erased_at is None


def test_help_builds() -> None:
    with pytest.raises(SystemExit):
        call_command("erase_contact", "--help", stdout=StringIO())

"""The admin's "Second factor reset" (#285): two superusers reset the second factors of a user
in no lab, through the services of #176. The services decide and record; these tests check the
page offers each step, shows their refusals, keeps out who may not, and shows the code once."""

import pyotp
import pytest
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.test import Client
from django.urls import reverse

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel
from cultures.core.testing import logged_in
from cultures.users import seeding
from cultures.users.factors import ConfirmOwnReset, ResetOwnFactor
from cultures.users.models import FactorReset, TotpDevice, User

from .conftest import make_user

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("behind_proxy")]
PROPOSE = "the person called from the institute's desk phone, checked by the head of IT"
CONFIRM = "checked again against the staff list"


def reset_url(user: User) -> str:
    return reverse("admin:users_user_factor_reset", args=[user.pk])


def change_url(user: User) -> str:
    return reverse("admin:users_user_change", args=[user.pk])


@pytest.fixture
def person() -> User:
    """A staff user in no lab with an authenticator app, the one who lost it."""
    user = make_user("operator", is_staff=True)
    with audit_context(
        channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label="command:test"
    ):
        seeding.totp(user, pyotp.random_base32())
    return user


@pytest.fixture
def second() -> User:
    return make_user("second-root", is_staff=True, is_superuser=True)


def step(client: Client, user: User, name: str, reason: str = PROPOSE) -> str:
    return client.post(
        reset_url(user), {"step": name, "reason": reason}, follow=True
    ).content.decode()


def open_resets(user: User) -> int:
    return FactorReset.objects.filter(user=user, confirmed_at=None, withdrawn_at=None).count()


def test_a_superuser_proposes_and_another_confirms_and_hands_over_the_code(
    admin_client: Client, staff: User, second: User, person: User
) -> None:
    person_session = logged_in(person)
    step(admin_client, person, "propose")
    reset = FactorReset.objects.get(user=person)
    assert (reset.proposed_by, reset.lab, reset.reason) == (staff, None, PROPOSE)

    page = step(logged_in(second), person, "confirm", CONFIRM)
    assert "Hand them this enrolment code in person" in page
    assert not TotpDevice.objects.filter(user=person).exists()
    assert not Session.objects.filter(pk=person_session.session.session_key).exists()
    events = AuditEvent.objects.filter(subject_id=person.public_id).order_by("pk")
    assert [(e.event_type, e.actor, e.reason) for e in events][-3:] == [
        ("factor_reset_proposed", staff, PROPOSE),
        ("factor_reset_confirmed", second, CONFIRM),
        ("enrolment_code_issued", second, CONFIRM),
    ]


def test_the_code_is_shown_once(admin_client: Client, second: User, person: User) -> None:
    step(admin_client, person, "propose")
    deputy = logged_in(second)
    page = step(deputy, person, "confirm", CONFIRM)
    code = page.split("it is not shown again: <code>")[1].split("</code>")[0]
    assert code
    assert code not in deputy.get(reset_url(person)).content.decode()
    assert code not in deputy.get(change_url(person)).content.decode()


def test_the_proposer_does_not_confirm(admin_client: Client, person: User) -> None:
    step(admin_client, person, "propose")
    page = step(admin_client, person, "confirm", CONFIRM)
    assert ConfirmOwnReset.default_detail in page
    assert open_resets(person) == 1
    assert TotpDevice.objects.filter(user=person).exists()


def test_the_person_does_not_confirm_their_own_reset(admin_client: Client, person: User) -> None:
    person.is_superuser = True
    person.save()
    step(admin_client, person, "propose")
    page = step(logged_in(person), person, "confirm", CONFIRM)
    assert ResetOwnFactor.default_detail in page
    assert open_resets(person) == 1


def test_a_reason_is_required(admin_client: Client, person: User) -> None:
    page = step(admin_client, person, "propose", reason="  ")
    assert "This field is required." in page
    assert not FactorReset.objects.exists()


def test_either_superuser_withdraws_an_open_reset(
    admin_client: Client, second: User, person: User
) -> None:
    step(admin_client, person, "propose")
    step(logged_in(second), person, "withdraw", "the person found the key")
    reset = FactorReset.objects.get(user=person)
    assert (reset.withdrawn_by, reset.confirmed_at) == (second, None)
    assert TotpDevice.objects.filter(user=person).exists()


def test_the_open_reset_is_listed_on_the_users_page(
    admin_client: Client, staff: User, person: User
) -> None:
    assert "Reset the second factor" in admin_client.get(change_url(person)).content.decode()
    step(admin_client, person, "propose")
    page = admin_client.get(change_url(person)).content.decode()
    assert f"A reset proposed by {staff} on" in page


def test_staff_who_are_not_superusers_see_nothing_of_it(person: User) -> None:
    clerk = make_user("clerk", is_staff=True)
    clerk.user_permissions.add(
        *Permission.objects.filter(codename__in=["view_user", "change_user"])
    )
    client = logged_in(clerk)
    assert client.get(reset_url(person)).status_code == 403
    assert client.post(reset_url(person), {"step": "propose", "reason": PROPOSE}).status_code == 403
    assert "Reset the second factor" not in client.get(change_url(person)).content.decode()
    assert not FactorReset.objects.exists()

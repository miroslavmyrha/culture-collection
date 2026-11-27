"""A user who lost every factor and every recovery code (#176): two people take the factors
away, a manager of the user's lab proposes and another one confirms, never the user; the user
enrols again at the next sign-in. The database holds the same rules."""

from typing import Any

import pyotp
import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import Client

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.core.exceptions import Forbidden, RuleViolation
from cultures.core.testing import assert_problem, logged_in
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import make_lab, member_of
from cultures.users import factors
from cultures.users.models import FactorReset, RecoveryCode, SecurityKey, TotpDevice, User

from .soft_key import SoftKey

pytestmark = pytest.mark.django_db
PASSWORD = "correct horse battery"  # noqa: S105 (a test password)
PROPOSE = "/api/v1/auth/factor-resets/propose/"


@pytest.fixture
def lab() -> Lab:
    return make_lab(name="Mycology", code="MYC")


@pytest.fixture
def first(lab: Lab) -> User:
    return member_of(lab, Role.MANAGER, "first-manager")


@pytest.fixture
def second(lab: Lab) -> User:
    return member_of(lab, Role.MANAGER, "second-manager")


@pytest.fixture
def person(lab: Lab) -> User:
    """A technician whose authenticator app is lost, with a password to sign in again."""
    user = member_of(lab, Role.TECHNICIAN, "lost-key")
    user.set_password(PASSWORD)
    user.save()
    with audit_context(channel=Channel.COMMAND, actor=user):
        factors.totp_enrol(
            user=user, secret=(secret := pyotp.random_base32()), code=pyotp.TOTP(secret).now()
        )
        factors.recovery_codes_issue(user=user)
    return user


def member_id(user: User, lab: Lab) -> str:
    return str(Membership.objects.get(user=user, lab=lab).public_id)


def post(client: Client, url: str, body: dict[str, Any]) -> Any:
    return client.post(url, body, content_type="application/json")


def propose(client: Client, person: User, lab: Lab) -> Any:
    return post(client, PROPOSE, {"member": member_id(person, lab), "reason": "Lost the phone."})


@pytest.mark.rule("R-ACCESS-04")
def test_two_managers_take_every_factor_away(
    lab: Lab, first: User, second: User, person: User
) -> None:
    signed_in = logged_in(person)
    proposed = propose(logged_in(first), person, lab)
    assert proposed.status_code == 201, proposed.content
    assert proposed.json()["may_confirm"] is False  # the proposer
    reset = proposed.json()["public_id"]
    listed = logged_in(second).get(f"/api/v1/auth/factor-resets/?lab={lab.public_id}").json()
    assert [(r["public_id"], r["may_confirm"]) for r in listed] == [(reset, True)]

    confirmed = post(
        logged_in(second),
        f"/api/v1/auth/factor-resets/{reset}/confirm/",
        {"reason": "Checked in person."},
    )
    assert confirmed.status_code == 200, confirmed.content
    assert not TotpDevice.objects.filter(user=person).exists()
    assert not RecoveryCode.objects.filter(user=person).exists()
    # The person's sessions end, and the next sign-in enrols again.
    assert_problem(signed_in.get("/api/v1/auth/me/"), 401, "not_authenticated")
    # The confirmer gets the enrolment code to hand over, and the person enrols with it.
    code = confirmed.json()["enrolment_code"]
    assert code
    again = Client()
    step = post(again, "/api/v1/auth/login/", {"username": "lost-key", "password": PASSWORD})
    assert step.json()["step"] == "enrol"
    assert post(again, "/api/v1/auth/enrolment-code/", {"code": code}).status_code == 204
    events = AuditEvent.objects.filter(event_type__startswith="factor_reset").order_by("pk")
    assert [(e.event_type, e.reason) for e in events] == [
        ("factor_reset_proposed", "Lost the phone."),
        ("factor_reset_confirmed", "Checked in person."),
    ]
    issued = AuditEvent.objects.get(event_type="enrolment_code_issued")
    assert (issued.actor, issued.reason) == (second, "Checked in person.")


@pytest.mark.rule("R-ACCESS-04")
def test_the_proposer_does_not_confirm(lab: Lab, first: User, person: User) -> None:
    reset = propose(logged_in(first), person, lab).json()["public_id"]
    refused = post(
        logged_in(first), f"/api/v1/auth/factor-resets/{reset}/confirm/", {"reason": "Alone."}
    )
    assert_problem(refused, 422, "confirm_own_reset")
    assert TotpDevice.objects.filter(user=person).exists()


@pytest.mark.rule("R-ACCESS-04")
def test_nobody_resets_their_own_factor(lab: Lab, first: User, second: User) -> None:
    refused = propose(logged_in(first), first, lab)
    assert_problem(refused, 422, "reset_own_factor")


@pytest.mark.rule("R-ACCESS-04")
def test_a_curator_does_not_propose(lab: Lab, first: User, person: User) -> None:
    curator = member_of(lab, Role.CURATOR, "curator")
    assert_problem(propose(logged_in(curator), person, lab), 404, "not_found")


def test_a_manager_of_another_lab_does_not_see_the_member(lab: Lab, person: User) -> None:
    stranger = member_of(make_lab(name="Bacteriology", code="BAC"), Role.MANAGER, "stranger")
    assert_problem(propose(logged_in(stranger), person, lab), 404, "not_found")


def test_a_withdrawn_reset_takes_nothing_away(
    lab: Lab, first: User, second: User, person: User
) -> None:
    reset = propose(logged_in(first), person, lab).json()["public_id"]
    withdrawn = post(
        logged_in(first), f"/api/v1/auth/factor-resets/{reset}/withdraw/", {"reason": "Found it."}
    )
    assert withdrawn.status_code == 200
    refused = post(
        logged_in(second), f"/api/v1/auth/factor-resets/{reset}/confirm/", {"reason": "Late."}
    )
    assert_problem(refused, 409, "reset_closed")
    assert TotpDevice.objects.filter(user=person).exists()


def test_a_reason_is_needed(lab: Lab, first: User, person: User) -> None:
    refused = post(logged_in(first), PROPOSE, {"member": member_id(person, lab), "reason": " "})
    assert refused.status_code == 400


def test_one_open_reset_per_person(lab: Lab, first: User, second: User, person: User) -> None:
    propose(logged_in(first), person, lab)
    assert_problem(propose(logged_in(second), person, lab), 409, "reset_exists")


# --- the database ------------------------------------------------------------------------------


def open_reset(lab: Lab, first: User, person: User) -> FactorReset:
    with audit_context(channel=Channel.COMMAND, actor=first):
        return factors.factor_reset_propose(actor=first, user=person, lab=lab, reason="Lost.")


def confirm_directly(reset: FactorReset, by: User) -> None:
    with connection.cursor() as cursor, transaction.atomic():
        cursor.execute(
            "UPDATE users_factorreset SET confirmed_by_id = %s, confirmed_at = now(),"
            " confirm_reason = 'x' WHERE id = %s",
            [by.pk, reset.pk],
        )


@pytest.mark.rule("R-ACCESS-04")
def test_the_database_refuses_a_confirmation_by_the_proposer(
    lab: Lab, first: User, person: User
) -> None:
    reset = open_reset(lab, first, person)
    with pytest.raises(IntegrityError, match="confirmed_by_another"):
        confirm_directly(reset, first)


@pytest.mark.rule("R-ACCESS-04")
def test_the_database_refuses_a_confirmation_by_the_user(
    lab: Lab, first: User, person: User
) -> None:
    reset = open_reset(lab, first, person)
    # The guard refuses first (the person is no manager); the check would refuse too.
    with pytest.raises(DatabaseError, match=r"confirmed_by_another|confirmed by a manager"):
        confirm_directly(reset, person)


@pytest.mark.rule("R-ACCESS-04")
@pytest.mark.parametrize("role", [Role.CURATOR, Role.TECHNICIAN, Role.VIEWER])
def test_the_database_refuses_a_confirmation_by_a_non_manager(
    lab: Lab, first: User, person: User, role: Role
) -> None:
    reset = open_reset(lab, first, person)
    other = member_of(lab, role, f"other-{role}")
    with pytest.raises(DatabaseError, match="confirmed by a manager"):
        confirm_directly(reset, other)


@pytest.mark.rule("R-ACCESS-04")
def test_the_database_refuses_a_proposal_by_a_non_manager(lab: Lab, person: User) -> None:
    curator = member_of(lab, Role.CURATOR, "curator")
    with connection.cursor() as cursor, pytest.raises(DatabaseError, match="manager of a lab"):
        cursor.execute(
            "INSERT INTO users_factorreset (public_id, created_at, updated_at, user_id, lab_id,"
            " proposed_by_id, reason, confirm_reason, withdraw_reason)"
            " VALUES (gen_random_uuid(), now(), now(), %s, %s, %s, 'x', '', '')",
            [person.pk, lab.pk, curator.pk],
        )


def test_the_database_never_deletes_a_reset(lab: Lab, first: User, person: User) -> None:
    reset = open_reset(lab, first, person)
    with connection.cursor() as cursor, pytest.raises(DatabaseError, match="never deleted"):
        cursor.execute("DELETE FROM users_factorreset WHERE id = %s", [reset.pk])


# --- the services, rule by rule (#308) ----------------------------------------------------------


def as_user(user: User) -> Any:
    return audit_context(channel=Channel.COMMAND, actor=user)


def add_key(user: User) -> None:
    """A security key next to the app, enrolled through the service."""
    ceremony = factors.key_registration(user, "localhost")
    credential = SoftKey().register(ceremony.options)
    with as_user(user):
        factors.key_enrol(
            user=user,
            credential=credential,
            challenge=ceremony.challenge,
            rp_id="localhost",
            origins=["http://localhost"],
            name="Blue key",
        )


def event(event_type: str) -> AuditEvent:
    return AuditEvent.objects.filter(event_type=event_type).order_by("-pk").first() or pytest.fail(
        f"no {event_type}"
    )


@pytest.mark.rule("R-ACCESS-04")
def test_each_step_of_a_reset_leaves_its_exact_trail(
    lab: Lab, first: User, second: User, person: User
) -> None:
    add_key(person)
    add_key(person)
    logged_in(person)
    with as_user(first):
        reset = factors.factor_reset_propose(actor=first, user=person, lab=lab, reason="Lost.")
    proposed = event("factor_reset_proposed")
    assert (proposed.changes, proposed.lab_id) == (
        {"factor_reset": [None, str(reset.public_id)]},
        lab.pk,
    )
    with as_user(second):
        factors.factor_reset_confirm(actor=second, reset=reset, reason="Checked in person.")
    confirmed = event("factor_reset_confirmed")
    assert (confirmed.changes, confirmed.lab_id) == (
        {
            "factor_reset": [None, str(reset.public_id)],
            "security_keys": [2, 0],
            "totp": [1, 0],
            "recovery_codes": [10, 0],
            "sessions": [1, 0],
        },
        lab.pk,
    )
    assert not SecurityKey.objects.filter(user=person).exists()

    with as_user(first):
        again = factors.factor_reset_propose(actor=first, user=person, lab=lab, reason="Lost.")
    with as_user(second):
        factors.factor_reset_withdraw(actor=second, reset=again, reason="Found it.")
    withdrawn = event("factor_reset_withdrawn")
    assert (withdrawn.changes, withdrawn.lab_id) == (
        {"factor_reset": [str(again.public_id), None]},
        lab.pk,
    )


def test_a_reason_is_required_word_for_word(lab: Lab, first: User, person: User) -> None:
    with as_user(first), pytest.raises(RuleViolation) as refused:
        factors.factor_reset_propose(actor=first, user=person, lab=lab, reason="  ")
    assert (refused.value.detail, refused.value.code, refused.value.attr) == (
        "A reason is required.",
        "reason_required",
        "reason",
    )


@pytest.mark.rule("R-ACCESS-04")
def test_an_inactive_manager_decides_nothing(lab: Lab, first: User, person: User) -> None:
    first.is_active = False
    first.save()
    with as_user(first), pytest.raises(Forbidden):
        factors.factor_reset_propose(actor=first, user=person, lab=lab, reason="Lost.")
    assert not FactorReset.objects.exists()


@pytest.mark.rule("R-ACCESS-04")
def test_a_manager_decides_only_for_a_member_of_the_lab(lab: Lab, first: User) -> None:
    stranger = member_of(make_lab(name="Bacteria", code="BAC"), Role.TECHNICIAN, "stranger")
    with as_user(first), pytest.raises(Forbidden):
        factors.factor_reset_propose(actor=first, user=stranger, lab=lab, reason="Lost.")
    assert not FactorReset.objects.exists()


@pytest.mark.rule("R-ACCESS-04")
def test_a_curator_of_the_lab_decides_nothing(lab: Lab, first: User, person: User) -> None:
    """The lab has a manager (first): the curator is not one."""
    curator = member_of(lab, Role.CURATOR, "curator")
    with as_user(curator), pytest.raises(Forbidden):
        factors.factor_reset_propose(actor=curator, user=person, lab=lab, reason="Lost.")
    assert not FactorReset.objects.exists()

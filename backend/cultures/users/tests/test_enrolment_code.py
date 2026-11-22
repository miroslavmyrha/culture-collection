"""The first enrolment of a factor takes a manager's one-time code (#176): the password alone
never gets in. A manager of a lab the person belongs to issues it with a reason (a superuser for
a person in no lab), valid ENROLMENT_CODE_HOURS, used once; the database holds the same."""

from datetime import timedelta
from typing import Any

import pyotp
import pytest
import time_machine
from django.conf import settings
from django.db import DatabaseError, connection
from django.test import Client
from django.utils import timezone

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.core.testing import assert_problem, logged_in
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import make_lab, member_of
from cultures.users import factors
from cultures.users.models import EnrolmentCode, LoginFailures, User

pytestmark = pytest.mark.django_db
PASSWORD = "correct horse battery"  # noqa: S105 (a test password)
ISSUE, USE = "/api/v1/auth/enrolment-codes/", "/api/v1/auth/enrolment-code/"
SETUP = "/api/v1/auth/factors/totp/setup/"


@pytest.fixture
def lab() -> Lab:
    return make_lab(name="Mycology", code="MYC")


@pytest.fixture
def manager(lab: Lab) -> User:
    return member_of(lab, Role.MANAGER, "manager")


@pytest.fixture
def newcomer(lab: Lab) -> User:
    user = member_of(lab, Role.TECHNICIAN, "newcomer")
    user.set_password(PASSWORD)
    user.save()
    return user


def post(client: Client, url: str, body: dict[str, Any] | None = None) -> Any:
    return client.post(url, body or {}, content_type="application/json")


def issue(manager: User, person: User, lab: Lab) -> Any:
    member = str(Membership.objects.get(user=person, lab=lab).public_id)
    return post(logged_in(manager), ISSUE, {"member": member, "reason": "Started today."})


def password_step(client: Client, username: str = "newcomer") -> None:
    post(client, "/api/v1/auth/login/", {"username": username, "password": PASSWORD})


@pytest.mark.rule("R-ACCESS-05")
def test_a_manager_issues_a_code_and_the_newcomer_enrols_with_it(
    lab: Lab, manager: User, newcomer: User
) -> None:
    issued = issue(manager, newcomer, lab)
    assert issued.status_code == 201, issued.content
    body = issued.json()
    assert (body["username"], body["valid_hours"]) == ("newcomer", settings.ENROLMENT_CODE_HOURS)
    stored = EnrolmentCode.objects.get(user=newcomer)
    assert (stored.issued_by, stored.lab, stored.reason) == (manager, lab, "Started today.")
    assert body["code"] not in stored.code_hash  # hashed, shown once
    event = AuditEvent.objects.get(event_type="enrolment_code_issued")
    assert (event.actor, event.reason) == (manager, "Started today.")

    client = Client()
    password_step(client)
    assert post(client, USE, {"code": body["code"]}).status_code == 204
    secret = post(client, SETUP).json()["secret"]
    enrolled = post(client, "/api/v1/auth/factors/totp/", {"code": pyotp.TOTP(secret).now()})
    assert enrolled.status_code == 201
    assert client.get("/api/v1/auth/me/").json()["username"] == "newcomer"


@pytest.mark.rule("R-ACCESS-05")
def test_without_a_code_the_password_enrols_nothing(newcomer: User) -> None:
    client = Client()
    password_step(client)
    assert_problem(post(client, SETUP), 403, "enrolment_code_required")
    assert_problem(
        post(client, "/api/v1/auth/factors/keys/options/"), 403, "enrolment_code_required"
    )
    assert_problem(client.get("/api/v1/auth/me/"), 401, "not_authenticated")


@pytest.mark.rule("R-ACCESS-05")
def test_a_used_code_is_refused(lab: Lab, manager: User, newcomer: User) -> None:
    code = issue(manager, newcomer, lab).json()["code"]
    first = Client()
    password_step(first)
    assert post(first, USE, {"code": code}).status_code == 204
    second = Client()
    password_step(second)
    assert_problem(post(second, USE, {"code": code}), 422, "wrong_code")
    assert_problem(post(second, SETUP), 403, "enrolment_code_required")


@pytest.mark.rule("R-ACCESS-05")
def test_an_expired_code_is_refused(lab: Lab, manager: User, newcomer: User) -> None:
    code = issue(manager, newcomer, lab).json()["code"]
    later = timezone.now() + timedelta(hours=settings.ENROLMENT_CODE_HOURS, minutes=1)
    with time_machine.travel(later):
        client = Client()
        password_step(client)
        assert_problem(post(client, USE, {"code": code}), 422, "wrong_code")


@pytest.mark.rule("R-ACCESS-05")
def test_a_code_of_another_person_is_refused(lab: Lab, manager: User, newcomer: User) -> None:
    other = member_of(lab, Role.VIEWER, "other")
    other.set_password(PASSWORD)
    other.save()
    code = issue(manager, other, lab).json()["code"]
    client = Client()
    password_step(client)
    assert_problem(post(client, USE, {"code": code}), 422, "wrong_code")


def test_a_wrong_code_counts_as_a_failed_login(newcomer: User) -> None:
    client = Client()
    password_step(client)
    assert_problem(post(client, USE, {"code": "abcde-fghjk"}), 422, "wrong_code")
    assert LoginFailures.objects.filter(address="").exclude(account="").exists()


@pytest.mark.rule("R-ACCESS-05")
def test_a_curator_does_not_issue_a_code(lab: Lab, newcomer: User) -> None:
    curator = member_of(lab, Role.CURATOR, "curator")
    assert_problem(issue(curator, newcomer, lab), 404, "not_found")
    assert not EnrolmentCode.objects.exists()


def test_a_manager_of_another_lab_does_not_issue_one(lab: Lab, newcomer: User) -> None:
    stranger = member_of(make_lab(name="Bacteriology", code="BAC"), Role.MANAGER, "stranger")
    assert_problem(issue(stranger, newcomer, lab), 404, "not_found")


def test_an_account_with_a_factor_needs_no_code(lab: Lab, manager: User, newcomer: User) -> None:
    with audit_context(channel=Channel.COMMAND, actor=newcomer):
        secret = pyotp.random_base32()
        factors.totp_enrol(user=newcomer, secret=secret, code=pyotp.TOTP(secret).now())
    client = Client()
    password_step(client)
    assert_problem(post(client, USE, {"code": "abcde-fghjk"}), 403, "verify_first")


# --- the database ------------------------------------------------------------------------------


def stored_code(lab: Lab, manager: User, newcomer: User) -> EnrolmentCode:
    issue(manager, newcomer, lab)
    return EnrolmentCode.objects.get(user=newcomer)


@pytest.mark.rule("R-ACCESS-05")
def test_the_database_uses_a_code_once(lab: Lab, manager: User, newcomer: User) -> None:
    code = stored_code(lab, manager, newcomer)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE users_enrolmentcode SET used_at = now() WHERE id = %s", [code.pk])
        with pytest.raises(DatabaseError, match="used once"):
            cursor.execute(
                "UPDATE users_enrolmentcode SET used_at = now() + interval '1 s' WHERE id = %s",
                [code.pk],
            )


@pytest.mark.rule("R-ACCESS-05")
def test_the_database_refuses_a_use_after_the_code_expired(
    lab: Lab, manager: User, newcomer: User
) -> None:
    code = stored_code(lab, manager, newcomer)
    with connection.cursor() as cursor, pytest.raises(DatabaseError, match="before it expires"):
        cursor.execute(
            "UPDATE users_enrolmentcode SET used_at = expires_at + interval '1 minute'"
            " WHERE id = %s",
            [code.pk],
        )


@pytest.mark.rule("R-ACCESS-05")
def test_the_database_refuses_a_code_from_a_non_manager(lab: Lab, newcomer: User) -> None:
    curator = member_of(lab, Role.CURATOR, "curator")
    with connection.cursor() as cursor, pytest.raises(DatabaseError, match="issued unused"):
        cursor.execute(
            "INSERT INTO users_enrolmentcode (user_id, lab_id, issued_by_id, reason, code_hash,"
            " created_at, expires_at) VALUES (%s, %s, %s, 'x', 'x', now(), now() + interval"
            " '1 day')",
            [newcomer.pk, lab.pk, curator.pk],
        )


def test_the_database_never_deletes_a_code(lab: Lab, manager: User, newcomer: User) -> None:
    code = stored_code(lab, manager, newcomer)
    with connection.cursor() as cursor, pytest.raises(DatabaseError, match="never deleted"):
        cursor.execute("DELETE FROM users_enrolmentcode WHERE id = %s", [code.pk])

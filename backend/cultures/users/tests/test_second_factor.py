"""The second factor (ADR 0009, #176): the sign-in in two steps, enrolment at the next sign-in,
TOTP, security keys, recovery codes, removal, and what the login limits count."""

from datetime import timedelta
from typing import Any

import pyotp
import pytest
import time_machine
from django.conf import settings
from django.db import connection
from django.test import Client
from django.utils import timezone
from model_bakery import baker
from pytest_django.fixtures import Settings

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel, RowChange
from cultures.core.testing import assert_problem
from cultures.users import factors
from cultures.users.models import LoginFailures, RecoveryCode, SecurityKey, TotpDevice, User
from cultures.users.signin import PENDING, VERIFIED_AT

from .soft_key import SoftKey

pytestmark = pytest.mark.django_db
PASSWORD = "correct horse battery"  # noqa: S105 (a test password)
LOGIN, ME = "/api/v1/auth/login/", "/api/v1/auth/me/"
CODE = "/api/v1/auth/second-factor/"
KEY_OPTIONS, KEY = "/api/v1/auth/second-factor/key/options/", "/api/v1/auth/second-factor/key/"
TOTP_SETUP, TOTP = "/api/v1/auth/factors/totp/setup/", "/api/v1/auth/factors/totp/"
ENROL_KEY_OPTIONS, ENROL_KEY = "/api/v1/auth/factors/keys/options/", "/api/v1/auth/factors/keys/"
FACTORS, CODES = "/api/v1/auth/factors/", "/api/v1/auth/factors/recovery-codes/"
ORIGIN = "http://localhost"


@pytest.fixture
def user() -> User:
    u: User = baker.make(User, username="lab-tech")
    u.set_password(PASSWORD)
    u.save()
    return u


def post(client: Client, url: str, body: dict[str, Any] | None = None) -> Any:
    return client.post(url, body or {}, content_type="application/json", headers={"Origin": ORIGIN})


def password_step(client: Client, username: str = "lab-tech", password: str = PASSWORD) -> Any:
    return post(client, LOGIN, {"username": username, "password": password})


ENROLMENT_CODE = "/api/v1/auth/enrolment-code/"


def issue_code(user: User) -> str:
    """An enrolment code from a superuser, as for a person in no lab (#176)."""
    issuer = User.objects.filter(username="issuer").first() or baker.make(
        User, username="issuer", is_superuser=True, is_staff=True
    )
    with audit_context(channel=Channel.COMMAND, actor=issuer):
        return factors.enrolment_code_issue(actor=issuer, user=user, lab=None, reason="New user.")


def give_code(client: Client, username: str = "lab-tech") -> None:
    """Before the first enrolment of a person not signed in: the manager's code."""
    if "_auth_user_id" in client.session:
        return
    code = issue_code(User.objects.get(username=username))
    assert post(client, ENROLMENT_CODE, {"code": code}).status_code == 204


def enrol_totp(client: Client, username: str = "lab-tech") -> tuple[str, list[str]]:
    """The first factor at the sign-in: an authenticator app. Returns its secret and codes."""
    give_code(client, username)
    secret = post(client, TOTP_SETUP).json()["secret"]
    response = post(client, TOTP, {"code": pyotp.TOTP(secret).now()})
    assert response.status_code == 201, response.content
    return secret, response.json()["recovery_codes"]


def next_code(secret: str) -> str:
    """The code of the next time step (each step is taken once)."""
    return pyotp.TOTP(secret).at(timezone.now() + timedelta(seconds=30))


@pytest.fixture
def with_totp(user: User) -> tuple[str, list[str]]:
    client = Client()
    password_step(client)
    return enrol_totp(client)


# --- the password step signs nobody in ----------------------------------------------------------


@pytest.mark.rule("R-ACCESS-03")
def test_the_password_alone_signs_nobody_in(user: User) -> None:
    client = Client()
    response = password_step(client)
    assert response.json() == {"step": "enrol", "methods": []}
    assert_problem(client.get(ME), 401, "not_authenticated")
    assert_problem(client.get("/api/v1/labs/"), 401, "not_authenticated")


@pytest.mark.rule("R-ACCESS-03")
def test_an_account_without_a_factor_reaches_only_the_enrolment(user: User) -> None:
    client = Client()
    password_step(client)
    give_code(client)
    assert post(client, TOTP_SETUP).status_code == 200
    assert_problem(client.get(FACTORS), 401, "not_authenticated")
    assert_problem(post(client, CODES), 401, "not_authenticated")


def test_the_first_factor_signs_in_and_shows_ten_recovery_codes_once(user: User) -> None:
    client = Client()
    password_step(client)
    _secret, codes = enrol_totp(client)
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert client.get(ME).json()["username"] == "lab-tech"
    # Hashed: no code is stored as it was shown.
    stored = set(RecoveryCode.objects.values_list("code_hash", flat=True))
    assert not stored & set(codes)


def test_a_wrong_password_is_refused_as_before(user: User) -> None:
    assert_problem(password_step(Client(), password="wrong"), 400, "invalid_credentials")


# --- TOTP ---------------------------------------------------------------------------------------


def test_totp_signs_in_after_the_password(user: User, with_totp: tuple[str, list[str]]) -> None:
    secret, _ = with_totp
    client = Client()
    step = password_step(client).json()
    assert step == {"step": "second_factor", "methods": ["totp", "recovery_code"]}
    with time_machine.travel(timezone.now() + timedelta(seconds=30)):
        response = post(client, CODE, {"method": "totp", "code": pyotp.TOTP(secret).now()})
        assert response.status_code == 200
        assert client.get(ME).status_code == 200


@pytest.mark.rule("R-ACCESS-03")
def test_a_totp_code_is_taken_once(user: User, with_totp: tuple[str, list[str]]) -> None:
    secret, _ = with_totp
    with time_machine.travel(timezone.now() + timedelta(seconds=30)):
        code = pyotp.TOTP(secret).now()
        first, second = Client(), Client()
        password_step(first)
        assert post(first, CODE, {"method": "totp", "code": code}).status_code == 200
        password_step(second)
        assert_problem(post(second, CODE, {"method": "totp", "code": code}), 422, "wrong_code")
        assert_problem(second.get(ME), 401, "not_authenticated")


@pytest.mark.rule("R-ACCESS-03")
def test_a_wrong_totp_code_is_refused_and_counted(
    user: User, with_totp: tuple[str, list[str]]
) -> None:
    client = Client()
    password_step(client)
    before = LoginFailures.objects.filter(address="").exclude(account="").count()
    assert_problem(post(client, CODE, {"method": "totp", "code": "000000"}), 422, "wrong_code")
    # The account counter of ADR 0007 took the failure (the pair and the address did too).
    assert LoginFailures.objects.filter(address="").exclude(account="").count() == before + 1
    assert_problem(client.get(ME), 401, "not_authenticated")


def test_failures_of_the_second_factor_end_in_the_pair_back_off(
    user: User, with_totp: tuple[str, list[str]], settings: Settings
) -> None:
    settings.LOGIN_PAIR_MAX_FAILURES = 2
    client = Client()
    password_step(client)
    for _ in range(2):
        post(client, CODE, {"method": "totp", "code": "000000"})
    assert_problem(post(client, CODE, {"method": "totp", "code": "000000"}), 429, "throttled")


def test_the_secret_is_stored_encrypted_and_never_in_the_trail(
    user: User, with_totp: tuple[str, list[str]]
) -> None:
    secret, _ = with_totp
    stored = TotpDevice.objects.get(user=user).secret
    assert secret not in stored
    rows = RowChange.objects.filter(table_label="users.totpdevice").values("old", "new")
    assert rows.exists()
    assert secret not in str(list(rows))
    assert stored not in str(list(rows))
    assert secret not in str(list(AuditEvent.objects.values("changes")))


# --- recovery codes ----------------------------------------------------------------------------


@pytest.mark.rule("R-ACCESS-03")
def test_a_recovery_code_signs_in_once(user: User, with_totp: tuple[str, list[str]]) -> None:
    _, codes = with_totp
    first, second = Client(), Client()
    assert password_step(first).status_code == 200
    assert post(first, CODE, {"method": "recovery_code", "code": codes[0]}).status_code == 200
    password_step(second)
    refused = post(second, CODE, {"method": "recovery_code", "code": codes[0]})
    assert_problem(refused, 422, "wrong_code")
    assert AuditEvent.objects.filter(event_type="recovery_code_used").count() == 1


def test_a_recovery_code_is_read_without_its_dash_and_case(
    user: User, with_totp: tuple[str, list[str]]
) -> None:
    _, codes = with_totp
    client = Client()
    password_step(client)
    typed = codes[3].replace("-", " ").upper()
    assert post(client, CODE, {"method": "recovery_code", "code": typed}).status_code == 200


# --- security keys -----------------------------------------------------------------------------


def enrol_key(client: Client, key: SoftKey, username: str = "lab-tech") -> Any:
    give_code(client, username)
    options = post(client, ENROL_KEY_OPTIONS).json()["options"]
    return post(client, ENROL_KEY, {"credential": key.register(options), "name": "Blue key"})


def test_a_security_key_enrols_at_the_sign_in_and_then_signs_in(user: User) -> None:
    key = SoftKey()
    client = Client()
    password_step(client)
    enrolled = enrol_key(client, key)
    assert enrolled.status_code == 201, enrolled.content
    assert len(enrolled.json()["recovery_codes"]) == 10
    stored = SecurityKey.objects.get(user=user)
    assert (stored.name, bytes(stored.credential_id)) == ("Blue key", key.credential_id)

    again = Client()
    assert password_step(again).json()["methods"] == ["security_key", "recovery_code"]
    options = post(again, KEY_OPTIONS).json()["options"]
    assert post(again, KEY, {"credential": key.sign(options)}).status_code == 200
    assert again.get(ME).status_code == 200
    stored.refresh_from_db()
    assert stored.sign_count == 1


def signed_in_key(user: User) -> SoftKey:
    key = SoftKey()
    client = Client()
    password_step(client)
    assert enrol_key(client, key).status_code == 201
    return key


@pytest.mark.rule("R-ACCESS-03")
def test_a_key_answer_from_another_origin_is_refused(user: User) -> None:
    key = signed_in_key(user)
    client = Client()
    password_step(client)
    options = post(client, KEY_OPTIONS).json()["options"]
    refused = post(client, KEY, {"credential": key.sign(options, origin="https://evil.example")})
    assert_problem(refused, 422, "key_refused")
    assert_problem(client.get(ME), 401, "not_authenticated")


@pytest.mark.rule("R-ACCESS-03")
def test_a_cloned_key_is_refused_by_its_counter(user: User) -> None:
    key = signed_in_key(user)
    first = Client()
    password_step(first)
    options = post(first, KEY_OPTIONS).json()["options"]
    assert post(first, KEY, {"credential": key.sign(options, count=5)}).status_code == 200
    clone = Client()
    password_step(clone)
    options = post(clone, KEY_OPTIONS).json()["options"]
    assert_problem(post(clone, KEY, {"credential": key.sign(options, count=5)}), 422, "key_refused")


def test_a_key_answer_is_taken_once(user: User) -> None:
    key = signed_in_key(user)
    client = Client()
    password_step(client)
    options = post(client, KEY_OPTIONS).json()["options"]
    answer = key.sign(options)
    assert post(client, KEY, {"credential": answer}).status_code == 200
    post(client, "/api/v1/auth/logout/")
    password_step(client)
    # No new challenge: the old answer has nothing to answer.
    assert_problem(post(client, KEY, {"credential": answer}), 422, "key_refused")


def test_an_account_with_a_factor_cannot_enrol_before_it_gives_one(
    user: User, with_totp: tuple[str, list[str]]
) -> None:
    client = Client()
    password_step(client)
    assert_problem(post(client, TOTP_SETUP), 403, "verify_first")
    assert_problem(post(client, ENROL_KEY_OPTIONS), 403, "verify_first")


# --- the pending step --------------------------------------------------------------------------


def test_the_password_step_expires(user: User, with_totp: tuple[str, list[str]]) -> None:
    secret, _ = with_totp
    client = Client()
    password_step(client)
    later = timezone.now() + timedelta(seconds=settings.MFA_PENDING_SECONDS + 60)
    with time_machine.travel(later):
        code = pyotp.TOTP(secret).now()
        assert_problem(
            post(client, CODE, {"method": "totp", "code": code}), 401, "not_authenticated"
        )


def test_the_password_step_rotates_the_session_key(user: User) -> None:
    client = Client()
    client.get("/api/v1/auth/csrf/")
    session = client.session
    session["planted"] = True
    session.save()
    before = session.session_key
    password_step(client)
    assert client.session.session_key != before
    assert PENDING in client.session


# --- a session without a second factor ---------------------------------------------------------


@pytest.mark.rule("R-ACCESS-03")
def test_a_session_signed_in_without_the_second_factor_is_ended(user: User) -> None:
    client = Client()
    client.force_login(user)  # login() without the steps, as a session from before #176
    assert_problem(client.get(ME), 401, "not_authenticated")
    assert "_auth_user_id" not in client.session


@pytest.mark.rule("R-ACCESS-03")
def test_the_admin_sends_every_sign_in_to_the_app(user: User) -> None:
    client = Client()
    path = f"/{settings.ADMIN_PATH}login/"
    assert client.get(path).headers["Location"] == "/login"
    response = client.post(path, {"username": "lab-tech", "password": PASSWORD})
    assert (response.status_code, response.headers["Location"]) == (302, "/login")
    assert "_auth_user_id" not in client.session


def test_the_admin_takes_a_staff_session_only_with_the_second_factor(user: User) -> None:
    user.is_staff = True
    user.save()
    client = Client()
    client.force_login(user)
    index = client.get(f"/{settings.ADMIN_PATH}")
    assert index.status_code == 302
    assert "login" in index.headers["Location"]


# --- the user's own factors --------------------------------------------------------------------


def signed_in_with_totp(user: User) -> tuple[Client, str]:
    client = Client()
    password_step(client, user.username)
    secret, _ = enrol_totp(client, user.username)
    return client, secret


@pytest.mark.rule("R-ACCESS-03")
def test_the_last_factor_stays(user: User) -> None:
    client, _ = signed_in_with_totp(user)
    assert_problem(client.delete("/api/v1/auth/factors/totp/remove/"), 422, "last_factor")
    assert TotpDevice.objects.filter(user=user).exists()


@pytest.mark.rule("R-ACCESS-03")
def test_removal_needs_a_fresh_second_factor(user: User) -> None:
    client, secret = signed_in_with_totp(user)
    enrol_key(client, SoftKey())  # a second factor, so one may go
    session = client.session
    session[VERIFIED_AT] = session[VERIFIED_AT] - settings.MFA_STEP_UP_SECONDS - 1
    session.save()
    remove = "/api/v1/auth/factors/totp/remove/"
    assert_problem(client.delete(remove), 403, "step_up_required")
    assert post(client, CODE, {"method": "totp", "code": next_code(secret)}).status_code == 200
    assert client.delete(remove).status_code == 204
    assert not TotpDevice.objects.filter(user=user).exists()
    assert AuditEvent.objects.filter(event_type="second_factor_removed").count() == 1


def test_new_recovery_codes_replace_the_old_ones(user: User) -> None:
    client, _ = signed_in_with_totp(user)
    old = list(RecoveryCode.objects.filter(user=user).values_list("pk", flat=True))
    response = post(client, CODES)
    assert response.status_code == 201
    assert len(response.json()["recovery_codes"]) == 10
    assert not RecoveryCode.objects.filter(pk__in=old).exists()


def test_the_factor_list_shows_no_secret(user: User) -> None:
    client, secret = signed_in_with_totp(user)
    listed = client.get(FACTORS).json()
    assert listed == {"security_keys": [], "totp": True, "recovery_codes_left": 10, "fresh": True}
    assert secret not in str(listed)


# --- what the database holds -------------------------------------------------------------------


def test_the_database_keeps_a_recovery_code_used_once(user: User) -> None:
    from django.db import DatabaseError, transaction  # noqa: PLC0415

    signed_in_with_totp(user)
    code = RecoveryCode.objects.filter(user=user).first()
    assert code is not None
    with connection.cursor() as cursor:
        cursor.execute("UPDATE users_recoverycode SET used_at = now() WHERE id = %s", [code.pk])
        with pytest.raises(DatabaseError, match="used once"), transaction.atomic():
            cursor.execute("UPDATE users_recoverycode SET used_at = NULL WHERE id = %s", [code.pk])


def test_the_database_keeps_the_sign_count_from_going_down(user: User) -> None:
    from django.db import DatabaseError, transaction  # noqa: PLC0415

    signed_in_key(user)
    key = SecurityKey.objects.get(user=user)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE users_securitykey SET sign_count = 9 WHERE id = %s", [key.pk])
        with pytest.raises(DatabaseError, match="higher sign count"), transaction.atomic():
            cursor.execute("UPDATE users_securitykey SET sign_count = 3 WHERE id = %s", [key.pk])


@pytest.mark.rule("R-ACCESS-03")
def test_a_user_removes_one_of_their_keys(user: User) -> None:
    client, _ = signed_in_with_totp(user)
    assert enrol_key(client, SoftKey()).status_code == 201
    key = SecurityKey.objects.get(user=user)
    other = baker.make(User, username="other")
    other.set_password(PASSWORD)
    other.save()
    assert client.delete(f"/api/v1/auth/factors/keys/{key.public_id}/").status_code == 204
    assert not SecurityKey.objects.filter(user=user).exists()
    # Someone else's key is not found: the lookup is the signed-in user's own keys.
    client2, _ = signed_in_with_totp(other)
    assert enrol_key(client2, SoftKey()).status_code == 201
    theirs = SecurityKey.objects.get(user=other)
    assert_problem(
        client.delete(f"/api/v1/auth/factors/keys/{theirs.public_id}/"), 404, "not_found"
    )


def test_the_second_step_does_not_spend_the_login_budget(
    user: User, with_totp: tuple[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from cultures.users.api.views import LoginThrottle  # noqa: PLC0415

    secret, _ = with_totp
    monkeypatch.setattr(LoginThrottle, "rate", "2/min", raising=False)
    for offset in (30, 60):  # two whole sign-ins, a new time step each
        client = Client()
        with time_machine.travel(timezone.now() + timedelta(seconds=offset)):
            assert password_step(client).status_code == 200
            code = pyotp.TOTP(secret).now()
            assert post(client, CODE, {"method": "totp", "code": code}).status_code == 200
    assert_problem(password_step(Client()), 429, "throttled")  # the third password waits

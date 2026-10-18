"""Login limits that never lock an account for everyone (cultures.users.login_limits).

Every scenario runs through both doors, the API login and the admin login: they
share the counters, the cookie and the 429. A door answers "in", "wrong" (the
password check failed) or "limited" (429 before the password is checked).
"""

import ipaddress
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import time_machine
from django.conf import settings
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pytest_django.fixtures import Settings

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel, RowChange
from cultures.core.testing import assert_problem
from cultures.users import login_limits, services
from cultures.users.login_limits import Outcome
from cultures.users.models import LoginFailures, User

from .conftest import PASSWORD, make_user

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse as Response
else:
    Response = Any

pytestmark = pytest.mark.django_db

API_LOGIN = "/api/v1/auth/login/"
ADMIN_LOGIN = reverse("admin:login")
HOME, AWAY, NEW = "198.51.100.1", "198.51.100.2", "198.51.100.77"
Door = Callable[..., str]
API_ANSWERS = {200: "in", 400: "wrong", 429: "limited"}
ADMIN_ANSWERS = {302: "in", 200: "wrong", 429: "limited"}


def post_api(client: Client, username: str, password: str, ip: str = HOME) -> Response:
    response: Response = client.post(
        API_LOGIN,
        {"username": username, "password": password},
        content_type="application/json",
        REMOTE_ADDR=ip,
    )
    return response


def post_admin(client: Client, username: str, password: str, ip: str = HOME) -> Response:
    response: Response = client.post(
        ADMIN_LOGIN, {"username": username, "password": password, "next": "/"}, REMOTE_ADDR=ip
    )
    return response


def api(client: Client, username: str, password: str, ip: str = HOME) -> str:
    return API_ANSWERS[post_api(client, username, password, ip).status_code]


def admin(client: Client, username: str, password: str, ip: str = HOME) -> str:
    return ADMIN_ANSWERS[post_admin(client, username, password, ip).status_code]


DOORS = {"api": (api, post_api), "admin": (admin, post_admin)}


@pytest.fixture(params=sorted(DOORS))
def surface(request: pytest.FixtureRequest) -> str:
    name: str = request.param
    return name


@pytest.fixture
def door(surface: str) -> Door:
    return DOORS[surface][0]


@pytest.fixture
def post(surface: str) -> Callable[..., Response]:
    return DOORS[surface][1]


def staff_user(username: str) -> User:
    """Staff, so the admin login accepts the right password too."""
    user = make_user(username, is_staff=True)
    user.set_password(PASSWORD)
    user.save()
    return user


@pytest.fixture
def alice() -> User:
    return staff_user("alice")


@pytest.fixture
def bob() -> User:
    return staff_user("bob")


def known_browser(door: Door, username: str, ip: str = HOME) -> Client:
    """A browser that signed in before: it keeps the known-device cookie, not the session."""
    browser = Client()
    assert door(browser, username, PASSWORD, ip) == "in"
    drop_session(browser)
    return browser


def drop_session(browser: Client) -> None:
    """Signed out without Client.logout(), which would drop every cookie."""
    browser.cookies.pop(settings.SESSION_COOKIE_NAME, None)


def put_under_attack(door: Door, username: str, *, first: int = 0) -> None:
    """LOGIN_ACCOUNT_MAX_FAILURES wrong passwords, each from its own address and browser."""
    for n in range(first, first + settings.LOGIN_ACCOUNT_MAX_FAILURES):
        assert door(Client(), username, "wrong", f"203.0.113.{n}") == "wrong"


def under_attack_events() -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(event_type="login_account_under_attack"))


class TestAccountUnderAttack:
    def test_the_own_browser_gets_in_and_a_new_address_does_not(
        self, door: Door, alice: User
    ) -> None:
        browser = known_browser(door, "alice")
        put_under_attack(door, "alice")
        assert door(browser, "alice", PASSWORD, NEW) == "in"
        assert door(Client(), "alice", PASSWORD, NEW) == "limited"

    def test_without_the_cookie_even_the_right_password_waits_for_the_window(
        self, post: Callable[..., Response], door: Door, alice: User
    ) -> None:
        with time_machine.travel(timezone.now(), tick=False):
            put_under_attack(door, "alice")
            response = post(Client(), "alice", PASSWORD, NEW)
        assert_problem(response, 429, "throttled")
        assert int(response["Retry-After"]) == settings.LOGIN_ACCOUNT_WINDOW_SECONDS

    def test_a_known_browser_of_another_account_does_not_help(
        self, door: Door, alice: User, bob: User
    ) -> None:
        bobs_browser = known_browser(door, "bob")
        put_under_attack(door, "alice")
        assert door(bobs_browser, "alice", PASSWORD, NEW) == "limited"
        assert door(bobs_browser, "bob", PASSWORD, NEW) == "in"

    def test_a_password_change_revokes_the_known_browser(self, door: Door, alice: User) -> None:
        browser = known_browser(door, "alice")
        with audit_context(channel=Channel.COMMAND, actor=alice):
            services.user_set_password(user=alice, raw_password=PASSWORD)  # same text, new hash
        put_under_attack(door, "alice")
        assert door(browser, "alice", PASSWORD, NEW) == "limited"

    def test_a_tampered_cookie_is_no_proof(self, door: Door, alice: User) -> None:
        browser = known_browser(door, "alice")
        value = browser.cookies[settings.KNOWN_DEVICE_COOKIE_NAME].value
        browser.cookies[settings.KNOWN_DEVICE_COOKIE_NAME] = value[:-2] + "xx"
        put_under_attack(door, "alice")
        assert door(browser, "alice", PASSWORD, NEW) == "limited"

    def test_a_cookie_older_than_its_age_is_no_proof(self, door: Door, alice: User) -> None:
        start = timezone.now()
        with time_machine.travel(start, tick=False) as clock:
            browser = known_browser(door, "alice")
            clock.shift(timedelta(seconds=settings.KNOWN_DEVICE_COOKIE_AGE + 1))
            put_under_attack(door, "alice")
            assert door(browser, "alice", PASSWORD, NEW) == "limited"

    def test_the_known_browser_still_has_its_own_pair_back_off(
        self, door: Door, alice: User
    ) -> None:
        browser = known_browser(door, "alice")
        put_under_attack(door, "alice")
        for _ in range(settings.LOGIN_PAIR_MAX_FAILURES):
            assert door(browser, "alice", "wrong", NEW) == "wrong"
        assert door(browser, "alice", PASSWORD, NEW) == "limited"

    def test_the_window_ends_and_everyone_may_try_again(self, door: Door, alice: User) -> None:
        window = timedelta(seconds=settings.LOGIN_ACCOUNT_WINDOW_SECONDS)
        with time_machine.travel(timezone.now(), tick=False) as clock:
            put_under_attack(door, "alice")
            clock.shift(window - timedelta(seconds=1))
            assert door(Client(), "alice", PASSWORD, NEW) == "limited"
            clock.shift(timedelta(seconds=1))
            assert door(Client(), "alice", PASSWORD, NEW) == "in"

    def test_an_unknown_name_is_refused_with_the_same_answer(
        self, post: Callable[..., Response], door: Door, alice: User
    ) -> None:
        with time_machine.travel(timezone.now(), tick=False):
            put_under_attack(door, "alice")
            put_under_attack(door, "nobody", first=100)
            real = post(Client(), "alice", PASSWORD, NEW)
            unknown = post(Client(), "nobody", PASSWORD, NEW)
        assert_problem(unknown, 429, "throttled")
        assert unknown.json() == real.json()
        assert unknown["Retry-After"] == real["Retry-After"]

    def test_folded_names_are_one_account(self, door: Door, alice: User) -> None:
        fullwidth = {code: code + 0xFEE0 for code in range(0x21, 0x7F)}
        names = [" ALICE", "Alice ", "alice".translate(fullwidth)]
        for n in range(settings.LOGIN_ACCOUNT_MAX_FAILURES):
            door(Client(), names[n % len(names)], "wrong", f"203.0.113.{n}")
        assert door(Client(), "alice", PASSWORD, NEW) == "limited"


class TestUnderAttackEvent:
    def test_an_existing_account_records_one_event_per_window(
        self, door: Door, surface: str, alice: User
    ) -> None:
        browser = known_browser(door, "alice")
        put_under_attack(door, "alice")
        door(browser, "alice", "wrong", NEW)  # a 21st failure, from the known browser
        (event,) = under_attack_events()
        assert (event.actor, event.actor_kind, event.actor_label) == (
            None,
            ActorKind.SYSTEM,
            "login-limits",
        )
        assert (event.subject_type, event.subject_id) == ("user", alice.public_id)
        assert event.channel == {"api": Channel.API, "admin": Channel.WEB}[surface]
        assert event.changes == {"login_under_attack": [False, True]}

    def test_the_event_carries_the_request_that_tripped_it(
        self, post: Callable[..., Response], alice: User
    ) -> None:
        for n in range(settings.LOGIN_ACCOUNT_MAX_FAILURES - 1):
            post(Client(), "alice", "wrong", f"203.0.113.{n}")
        assert under_attack_events() == []
        tripping = post(Client(), "alice", "wrong", NEW)
        (event,) = under_attack_events()
        assert event.request_id == tripping["X-Request-ID"]

    def test_a_new_window_records_again(self, door: Door, alice: User) -> None:
        window = timedelta(seconds=settings.LOGIN_ACCOUNT_WINDOW_SECONDS)
        with time_machine.travel(timezone.now(), tick=False) as clock:
            put_under_attack(door, "alice")
            clock.shift(window)
            put_under_attack(door, "alice", first=100)
        assert len(under_attack_events()) == 2

    def test_an_unknown_name_records_nothing(self, door: Door) -> None:
        put_under_attack(door, "nobody")
        assert under_attack_events() == []


class TestPair:
    def test_failures_from_one_address_hold_back_that_address_only(
        self, door: Door, alice: User
    ) -> None:
        attacker = Client()
        for _ in range(settings.LOGIN_PAIR_MAX_FAILURES):
            assert door(attacker, "alice", "wrong", HOME) == "wrong"
        assert door(Client(), "alice", PASSWORD, HOME) == "limited"
        assert door(Client(), "alice", PASSWORD, AWAY) == "in"

    def test_the_back_off_doubles_with_each_further_failure(
        self, post: Callable[..., Response], door: Door, alice: User
    ) -> None:
        base = timedelta(seconds=settings.LOGIN_PAIR_BACKOFF_SECONDS)
        with time_machine.travel(timezone.now(), tick=False) as clock:
            for _ in range(settings.LOGIN_PAIR_MAX_FAILURES):
                door(Client(), "alice", "wrong")
            response = post(Client(), "alice", PASSWORD)
            assert response.status_code == 429
            assert int(response["Retry-After"]) == base.total_seconds()
            clock.shift(base - timedelta(seconds=1))
            assert door(Client(), "alice", PASSWORD) == "limited"
            clock.shift(timedelta(seconds=1))
            assert door(Client(), "alice", "wrong") == "wrong"  # one more failure: twice as long
            clock.shift(2 * base - timedelta(seconds=1))
            assert door(Client(), "alice", PASSWORD) == "limited"
            clock.shift(timedelta(seconds=1))
            assert door(Client(), "alice", PASSWORD) == "in"

    def test_the_back_off_never_outlasts_the_pair_window(
        self, post: Callable[..., Response], door: Door, alice: User, settings: Settings
    ) -> None:
        settings.LOGIN_PAIR_BACKOFF_SECONDS = settings.LOGIN_PAIR_WINDOW_SECONDS
        with time_machine.travel(timezone.now(), tick=False) as clock:
            for _ in range(settings.LOGIN_PAIR_MAX_FAILURES - 1):
                door(Client(), "alice", "wrong")
            clock.shift(timedelta(seconds=60))
            door(Client(), "alice", "wrong")  # the fifth, a minute into the window
            response = post(Client(), "alice", PASSWORD)
            assert int(response["Retry-After"]) == settings.LOGIN_PAIR_WINDOW_SECONDS - 60

    def test_a_success_clears_its_own_pair_only(self, door: Door, alice: User) -> None:
        for _ in range(settings.LOGIN_PAIR_MAX_FAILURES - 1):
            door(Client(), "alice", "wrong", HOME)
        door(Client(), "alice", "wrong", AWAY)
        assert door(Client(), "alice", PASSWORD, HOME) == "in"
        account = login_limits.account_key("alice")
        home, away = login_limits.address_key(HOME), login_limits.address_key(AWAY)
        assert counts() == {
            (account, away): 1,  # the pair of the other address stays
            (account, ""): settings.LOGIN_PAIR_MAX_FAILURES,
            ("", home): settings.LOGIN_PAIR_MAX_FAILURES - 1,
            ("", away): 1,
        }


def counts() -> dict[tuple[str, str], int]:
    return {(row.account, row.address): row.failures for row in LoginFailures.objects.all()}


class TestAddressBudget:
    def test_one_address_guessing_many_names_runs_out(self, door: Door, alice: User) -> None:
        attacker = Client()
        for n in range(settings.LOGIN_ADDRESS_MAX_FAILURES):
            assert door(attacker, f"name{n}", "wrong", HOME) == "wrong"
        assert door(attacker, "another-name", "wrong", HOME) == "limited"
        assert door(Client(), "alice", PASSWORD, HOME) == "limited"
        assert door(Client(), "alice", PASSWORD, AWAY) == "in"

    def test_a_known_browser_behind_a_spent_address_still_gets_in(
        self, door: Door, alice: User
    ) -> None:
        """A lab behind one NAT: other people's failures do not lock the real user out."""
        browser = known_browser(door, "alice")
        for n in range(settings.LOGIN_ADDRESS_MAX_FAILURES):
            door(Client(), f"name{n}", "wrong", HOME)
        assert door(browser, "alice", PASSWORD, HOME) == "in"

    @pytest.mark.parametrize("good_logins", [False, True])
    def test_good_logins_in_between_do_not_reset_the_budget(
        self, door: Door, alice: User, settings: Settings, good_logins: bool
    ) -> None:
        """An attacker with an account of its own signs in between guesses: same limit."""
        settings.LOGIN_ADDRESS_MAX_FAILURES = 6
        mallory, mallorys_browser = staff_user("mallory"), Client()
        answers = []
        for n in range(settings.LOGIN_ADDRESS_MAX_FAILURES + 1):
            answers.append(door(Client(), f"victim{n}", "wrong", HOME))
            if good_logins:
                assert door(mallorys_browser, mallory.username, PASSWORD, HOME) == "in"
        assert answers == ["wrong"] * settings.LOGIN_ADDRESS_MAX_FAILURES + ["limited"]

    def test_ipv6_neighbours_share_the_budget(self, door: Door, settings: Settings) -> None:
        settings.LOGIN_ADDRESS_MAX_FAILURES = 2
        assert door(Client(), "a", "wrong", "2001:db8:1:2::1") == "wrong"
        assert door(Client(), "b", "wrong", "2001:db8:1:2::2") == "wrong"
        assert door(Client(), "c", "wrong", "2001:db8:1:2::3") == "limited"
        assert door(Client(), "d", "wrong", "2001:db8:1:3::1") == "wrong"

    def test_a_forged_forwarding_header_is_the_same_address(
        self, door: Door, settings: Settings
    ) -> None:
        settings.LOGIN_ADDRESS_MAX_FAILURES = 2
        for n in range(2):
            assert door(_forwarded(Client(), f"203.0.113.{n}"), f"name{n}", "wrong") == "wrong"
        assert door(_forwarded(Client(), "203.0.113.9"), "name9", "wrong") == "limited"

    def test_behind_a_trusted_proxy_the_budget_is_per_client(
        self, door: Door, settings: Settings
    ) -> None:
        settings.LOGIN_ADDRESS_MAX_FAILURES = 2
        settings.TRUSTED_PROXIES = (ipaddress.ip_network("10.0.0.5"),)
        for n in range(2):
            door(_forwarded(Client(), "203.0.113.1"), f"name{n}", "wrong", "10.0.0.5")
        assert door(_forwarded(Client(), "203.0.113.1"), "name9", "wrong", "10.0.0.5") == "limited"
        assert door(_forwarded(Client(), "203.0.113.2"), "name9", "wrong", "10.0.0.5") == "wrong"


def _forwarded(client: Client, address: str) -> Client:
    client.defaults["HTTP_X_FORWARDED_FOR"] = address
    return client


class TestKnownDeviceCookie:
    def test_every_login_sets_it_http_only_lax_for_a_year(
        self, post: Callable[..., Response], alice: User
    ) -> None:
        response = post(Client(), "alice", PASSWORD)
        cookie = response.cookies[settings.KNOWN_DEVICE_COOKIE_NAME]
        assert (cookie["httponly"], cookie["samesite"], cookie["path"]) == (True, "Lax", "/")
        assert cookie["max-age"] == settings.KNOWN_DEVICE_COOKIE_AGE == 365 * 24 * 60 * 60
        assert cookie["domain"] == ""  # a __Host- cookie must have none
        assert cookie["secure"] == ""  # development over http; production sets it (test_settings)
        assert "alice" not in cookie.value.lower()
        assert str(alice.public_id) not in cookie.value

    def test_a_failed_login_sets_no_cookie(
        self, post: Callable[..., Response], alice: User
    ) -> None:
        response = post(Client(), "alice", "wrong")
        assert settings.KNOWN_DEVICE_COOKIE_NAME not in response.cookies

    def test_one_browser_remembers_several_accounts(
        self, door: Door, alice: User, bob: User
    ) -> None:
        browser = Client()
        for name in ("alice", "bob", "alice"):  # alice again: replaced, not added twice
            assert door(browser, name, PASSWORD) == "in"
        value = browser.cookies[settings.KNOWN_DEVICE_COOKIE_NAME].value
        assert len(value.split("|")) == 2
        drop_session(browser)
        put_under_attack(door, "alice")
        put_under_attack(door, "bob", first=100)
        assert door(browser, "bob", PASSWORD, NEW) == "in"
        drop_session(browser)
        assert door(browser, "alice", PASSWORD, NEW) == "in"

    def test_the_oldest_account_drops_out_after_five(self, door: Door) -> None:
        browser = Client()
        names = [staff_user(f"user{n}").username for n in range(6)]
        for name in names:
            assert door(browser, name, PASSWORD) == "in"
        value = browser.cookies[settings.KNOWN_DEVICE_COOKIE_NAME].value
        assert len(value.split("|")) == login_limits.KNOWN_DEVICES_PER_BROWSER
        drop_session(browser)
        put_under_attack(door, names[0])
        put_under_attack(door, names[1], first=100)
        assert door(browser, names[0], PASSWORD, NEW) == "limited"
        drop_session(browser)
        assert door(browser, names[1], PASSWORD, NEW) == "in"


class TestNoUserNamesAnywhere:
    SECRETS = ("Secret-Pass-123", "alice@example.org")

    def test_a_password_typed_as_the_name_is_in_no_log_and_no_audit_row(
        self, door: Door, caplog: pytest.LogCaptureFixture
    ) -> None:
        make_user("alice@example.org")  # an existing account too: it goes under attack
        events, rows = _last_audit_ids()
        with caplog.at_level(logging.DEBUG):
            for typed in self.SECRETS:
                for n in range(settings.LOGIN_ACCOUNT_MAX_FAILURES + 1):
                    door(Client(), typed, "wrong", f"203.0.113.{n}")
        login_lines = [r for r in caplog.records if r.name == "cultures.login"]
        assert len(login_lines) == 2 * (settings.LOGIN_ACCOUNT_MAX_FAILURES + 1)
        assert len(under_attack_events()) == 1  # the audit check below reads a real row
        logged = " ".join(_record_text(record) for record in caplog.records)
        audited = " ".join(_audit_text(events, rows))
        for secret in self.SECRETS:
            assert secret.lower() not in logged.lower()
            assert secret.lower() not in audited.lower()

    def test_the_same_name_has_the_same_account_ref_in_every_line(
        self, door: Door, surface: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="cultures.login"):
            door(Client(), "alice", "wrong")
            door(Client(), " ALICE ", "wrong")
            door(Client(), "bob", "wrong")
        refs = [
            record.__dict__["fields"]["account_ref"]
            for record in caplog.records
            if record.name == "cultures.login"
        ]
        assert refs[0] == refs[1] != refs[2]
        assert len(refs[0]) == 16 and int(refs[0], 16) >= 0
        assert refs[0] == login_limits.account_key("alice")[:16]


def _record_text(record: logging.LogRecord) -> str:
    return " ".join([record.getMessage(), repr(record.args), repr(getattr(record, "fields", ""))])


def _last_audit_ids() -> tuple[int, int]:
    last_event = AuditEvent.objects.order_by("-pk").values_list("pk", flat=True).first()
    last_row = RowChange.objects.order_by("-pk").values_list("pk", flat=True).first()
    return last_event or 0, last_row or 0


def _audit_text(after_event: int, after_row: int) -> list[str]:
    """Every value of every audit row written after the given ids."""
    values: list[Any] = [
        *AuditEvent.objects.filter(pk__gt=after_event).values_list(),
        *RowChange.objects.filter(pk__gt=after_row).values_list(),
    ]
    return [repr(row) for row in values]


class TestLogLine:
    @pytest.mark.parametrize(
        "case",
        [
            ("nothing", Outcome.BAD_CREDENTIALS),
            ("pair", Outcome.PAIR_LIMITED),
            ("address", Outcome.IP_LIMITED),
            ("account", Outcome.ACCOUNT_UNDER_ATTACK),
        ],
        ids=lambda case: str(case[1]),
    )
    def test_each_failure_and_refusal_writes_one_line(
        self,
        post: Callable[..., Response],
        surface: str,
        alice: User,
        caplog: pytest.LogCaptureFixture,
        case: tuple[str, Outcome],
    ) -> None:
        setup, outcome = case
        now = timezone.now()
        account, address = login_limits.account_key("alice"), login_limits.address_key(HOME)
        limits = {
            "pair": (account, address, settings.LOGIN_PAIR_MAX_FAILURES),
            "address": ("", address, settings.LOGIN_ADDRESS_MAX_FAILURES),
            "account": (account, "", settings.LOGIN_ACCOUNT_MAX_FAILURES),
        }
        if setup in limits:
            row_account, row_address, failures = limits[setup]
            LoginFailures.objects.create(
                account=row_account,
                address=row_address,
                window_ends_at=now + timedelta(minutes=10),
                last_failure_at=now,
                failures=failures,
            )
        with caplog.at_level(logging.WARNING, logger="cultures.login"):
            response = post(Client(), "alice", "wrong")
        (record,) = [r for r in caplog.records if r.name == "cultures.login"]
        assert record.__dict__["fields"] == {
            "event": "login_failed",
            "account_ref": account[:16],
            "ip_bucket": HOME,
            "surface": surface,
            "outcome": str(outcome),
            "request_id": response["X-Request-ID"],
        }
        assert record.getMessage() == (
            f"login_failed account_ref={account[:16]} ip_bucket={HOME}"
            f" surface={surface} outcome={outcome}"
        )

    def test_a_success_writes_no_line(
        self, door: Door, alice: User, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="cultures.login"):
            assert door(Client(), "alice", PASSWORD) == "in"
        assert [r for r in caplog.records if r.name == "cultures.login"] == []


class TestCounters:
    def test_a_flushed_or_culled_cache_resets_no_limit(self, door: Door, alice: User) -> None:
        """The counters left DatabaseCache: its cull deleted the login keys first."""
        put_under_attack(door, "alice")
        cache.clear()
        assert door(Client(), "alice", PASSWORD, NEW) == "limited"

    def test_the_table_holds_keys_and_counts_only(self, door: Door, alice: User) -> None:
        door(Client(), "alice", "wrong", HOME)
        rows = list(LoginFailures.objects.values_list("account", "address"))
        assert len(rows) == 3
        text = repr(rows)
        assert "alice" not in text and HOME not in text
        assert all(len(key) in {0, 64} for row in rows for key in row)

    def test_prune_deletes_ended_windows_and_keeps_live_ones(self) -> None:
        now = timezone.now()
        for n, ends in enumerate((now - timedelta(seconds=1), now, now + timedelta(seconds=1))):
            LoginFailures.objects.create(
                account=f"{n:064x}",
                address="",
                window_ends_at=ends,
                last_failure_at=now,
                failures=1,
            )
        assert login_limits.prune(now) == 2
        assert list(LoginFailures.objects.values_list("window_ends_at", flat=True)) == [
            now + timedelta(seconds=1)
        ]
        assert login_limits.prune(now) == 0

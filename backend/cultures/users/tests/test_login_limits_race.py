"""Failed logins that arrive at the same moment are all counted, and an attack is recorded once.

Real threads, each with its own connection, released together by a barrier
right before the upsert. A read-modify-write counter (DatabaseCache's incr is
a get plus a set) hands out the same count twice and loses failures; the
single INSERT ... ON CONFLICT DO UPDATE ... RETURNING hands out every count once.
"""

import threading
from collections.abc import Callable

import pytest
from django.db import connection
from django.test import RequestFactory
from django.utils import timezone
from pytest_django.fixtures import Settings

from cultures.audit.models import AuditEvent
from cultures.users import login_limits
from cultures.users.login_limits import Attempt, Surface
from cultures.users.models import LoginFailures, User

from .conftest import make_user

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow]
THREADS = 8


def together(call: Callable[[int], object]) -> list[object]:
    """Run call(index) in THREADS threads released at once. Returns the results by index."""
    start = threading.Barrier(THREADS, timeout=10)
    results: dict[int, object] = {}
    errors: list[BaseException] = []

    def run(index: int) -> None:
        try:
            start.wait()
            results[index] = call(index)
        except BaseException as error:  # noqa: BLE001 (reported by the assertion below)
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    return [results[i] for i in range(THREADS)]


@pytest.mark.parametrize("existing", [False, True], ids=["new counters", "existing counters"])
def test_parallel_failures_are_all_counted(existing: bool) -> None:
    account, address = login_limits.account_key("alice"), login_limits.address_key("192.0.2.1")
    before = 0
    if existing:
        login_limits.count_failure(account, address, timezone.now())
        before = 1
    results = together(lambda _: login_limits.count_failure(account, address, timezone.now()))
    pairs = sorted(result["pair"] for result in results)  # type: ignore[index]
    assert pairs == list(range(before + 1, before + THREADS + 1))  # every count handed out once
    counts = {(r.account, r.address): r.failures for r in LoginFailures.objects.all()}
    assert set(counts.values()) == {before + THREADS}


def test_an_attack_from_many_addresses_at_once_is_recorded_once(settings: Settings) -> None:
    settings.LOGIN_ACCOUNT_MAX_FAILURES = 3
    alice: User = make_user("alice")

    def fail(index: int) -> None:
        request = RequestFactory().post("/", REMOTE_ADDR=f"203.0.113.{index}")
        Attempt.of(request, "alice", Surface.API).failed()

    together(fail)
    (event,) = AuditEvent.objects.filter(event_type="login_account_under_attack")
    assert event.subject_id == alice.public_id
    (row,) = LoginFailures.objects.filter(account=login_limits.account_key("alice"), address="")
    assert row.failures == THREADS

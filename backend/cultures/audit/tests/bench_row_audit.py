"""The cost of the row audit triggers: measured, never asserted (machine dependent).

Not collected by the suite (python_files is test_*.py). Run it on its own:
    pytest cultures/audit/tests/bench_row_audit.py -s
Each round runs in a savepoint that is rolled back, with the triggers on, then
off (ALTER TABLE ... DISABLE TRIGGER inside the savepoint). The median of
ROUNDS rounds is printed for bulk_create and for one QuerySet.update().
"""

import statistics
import time
from collections.abc import Callable

import pytest
from django.db import connection, transaction

from cultures.audit.context import AuditContext, audited_atomic
from cultures.users.models import User

pytestmark = pytest.mark.django_db
ROWS = 10_000
ROUNDS = 5


def timed(action: Callable[[], object], *, triggers: bool) -> float:
    with transaction.atomic(), audited_atomic():
        if not triggers:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE users_user DISABLE TRIGGER USER")
        start = time.perf_counter()
        action()
        elapsed = time.perf_counter() - start
        transaction.set_rollback(True)
    return elapsed


def bulk_create() -> None:
    User.objects.bulk_create(
        [User(username=f"bench{i}", email=f"bench{i}@example.org") for i in range(ROWS)],
        batch_size=1000,
    )


def create_then_update() -> Callable[[], object]:
    def run() -> object:
        return User.objects.filter(username__startswith="bench").update(first_name="Bench")

    return run


SINGLE = 1_000


def single_row_updates() -> None:
    """The common case: one statement per row, as a service saving one object."""
    for pk in User.objects.filter(username__startswith="bench").values_list("pk", flat=True)[
        :SINGLE
    ]:
        User.objects.filter(pk=pk).update(first_name="Single")


def measure(action: Callable[[], object], *, setup: Callable[[], None] | None = None) -> str:
    results = {}
    for triggers in (True, False):
        samples = []
        for _ in range(ROUNDS):
            with transaction.atomic():
                if setup is not None:
                    with connection.cursor() as cursor:
                        cursor.execute("ALTER TABLE users_user DISABLE TRIGGER USER")
                    setup()
                    with connection.cursor() as cursor:
                        cursor.execute("ALTER TABLE users_user ENABLE TRIGGER USER")
                samples.append(timed(action, triggers=triggers))
                transaction.set_rollback(True)
        results[triggers] = statistics.median(samples)
    on, off = results[True], results[False]
    return f"with triggers {on * 1000:.0f} ms, without {off * 1000:.0f} ms, ratio {on / off:.1f}x"


def test_measure_row_audit_overhead(audited: AuditContext) -> None:
    print(f"\nbulk_create of {ROWS} users: {measure(bulk_create)}")  # noqa: T201
    print(  # noqa: T201
        f"update() of {ROWS} users: {measure(create_then_update(), setup=bulk_create)}"
    )
    print(  # noqa: T201
        f"{SINGLE} single-row update() calls: {measure(single_row_updates, setup=bulk_create)}"
    )

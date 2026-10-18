"""Two accessions in one lab at the same moment get two numbers, never the same one.

Real threads and real transactions, each with its own connection and audit context.
Two points are forced:
- the threads meet at the lab lock (the first lock_lab call of each), so both arrive
  there with the counter still ahead of them;
- the first thread past the counter (_next_seq) waits a moment for the other one. With
  the lab lock the other cannot get there before the first commits, so the wait times
  out and the second thread then reads the committed counter. Without the lock both
  read the same counter value, and one accession fails on the unique sequence: the
  assertions fail every time, not only when the timing is unlucky.
"""

import contextlib
import threading
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.labs import locks
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.strains import services
from cultures.strains.models import Strain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .conftest import new_strain

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow]
AFTER_COUNTER_WAIT = 1.5  # seconds the first thread past the counter waits for the other one


def _wait(barrier: threading.Barrier) -> None:
    with contextlib.suppress(threading.BrokenBarrierError):
        barrier.wait()


def race(
    monkeypatch: pytest.MonkeyPatch, calls: list[tuple[User, Callable[[], object]]]
) -> list[str]:
    at_lock = threading.Barrier(2, timeout=5)
    after_counter = threading.Barrier(2, timeout=AFTER_COUNTER_WAIT)
    seen = threading.local()
    lock_lab: Callable[[int], Lab] = locks.lock_lab
    next_seq: Callable[[Lab], int] = services._next_seq

    def meet_at_lock(lab_id: int) -> Lab:
        if not getattr(seen, "lock", False):
            seen.lock = True
            _wait(at_lock)
        return lock_lab(lab_id)

    def wait_after_counter(*args: Any) -> int:
        seq = next_seq(*args)
        if not getattr(seen, "counter", False):
            seen.counter = True
            _wait(after_counter)
        return seq

    monkeypatch.setattr(services, "lock_lab", meet_at_lock)
    monkeypatch.setattr(services, "_next_seq", wait_after_counter)
    outcomes: dict[int, str] = {}

    def run(index: int, actor: User, call: Callable[[], object]) -> None:
        try:
            with audit_context(channel=Channel.API, actor=actor):
                call()
            outcomes[index] = "done"
        except Exception as error:  # noqa: BLE001 (the outcome is the assertion)
            outcomes[index] = type(error).__name__
        finally:
            connection.close()

    threads = [
        threading.Thread(target=run, args=(i, actor, call)) for i, (actor, call) in enumerate(calls)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return [outcomes.get(i, "no outcome") for i in range(len(calls))]


@pytest.mark.parametrize("earlier", [0, 3])
def test_two_accessions_at_once_get_two_numbers(
    *,
    earlier: int,
    lab: Lab,
    curator: User,
    manager: User,
    subtilis: Taxon,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no counter row yet (the lab's first strain) and with one that exists."""
    if earlier:
        for _ in range(earlier):
            with audit_context(channel=Channel.API, actor=curator):
                services.strain_create(
                    access=access_for(curator), lab=lab, data=new_strain(subtilis)
                )

    def accession(actor: User) -> tuple[User, Callable[[], object]]:
        return actor, lambda: services.strain_create(
            access=access_for(actor),
            lab=lab,
            data=new_strain(subtilis, name_as_received=f"by {actor.username}"),
        )

    outcomes = race(monkeypatch, [accession(curator), accession(manager)])
    assert outcomes == ["done", "done"]
    seqs = sorted(
        s for s in Strain.objects.filter(lab=lab).values_list("accession_seq", flat=True) if s
    )
    assert seqs == list(range(1, earlier + 3))
    assert AuditEvent.objects.filter(event_type="strain_created").count() == earlier + 2

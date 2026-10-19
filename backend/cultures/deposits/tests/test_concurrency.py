"""Two acceptances of one deposit at the same moment give one strain and one number.

Real threads and real transactions, each with its own connection and audit context. The
threads meet at the lab lock (the first lock_lab call of each), so both arrive with the
deposit still checking. The lab lock lets one through; the other then reads the committed
deposit, accepted, and is refused with deposit_state. Without the lock both would read
"checking", and the second would either take a second number or fail on the deposit's
guard: the assertions name which.
"""

import contextlib
import threading
from collections.abc import Callable

import pytest
from django.db import connection

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.deposits import services
from cultures.deposits.models import Deposit, DepositStatus
from cultures.labs import locks
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.lineage.models import Passage
from cultures.strains.models import Strain, StrainCounter
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import MakeDeposit, facts

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow]


def race(
    monkeypatch: pytest.MonkeyPatch, calls: list[tuple[User, Callable[[], object]]]
) -> list[str]:
    at_lock = threading.Barrier(2, timeout=5)
    seen = threading.local()
    lock_lab: Callable[[int], Lab] = locks.lock_lab

    def meet_at_lock(lab_id: int) -> Lab:
        if not getattr(seen, "lock", False):
            seen.lock = True
            with contextlib.suppress(threading.BrokenBarrierError):
                at_lock.wait()
        return lock_lab(lab_id)

    monkeypatch.setattr(services, "lock_lab", meet_at_lock)
    outcomes: dict[int, str] = {}

    def run(index: int, actor: User, call: Callable[[], object]) -> None:
        try:
            with audit_context(channel=Channel.API, actor=actor):
                call()
            outcomes[index] = "done"
        except Exception as error:  # noqa: BLE001 (the outcome is the assertion)
            outcomes[index] = getattr(error, "code", type(error).__name__)
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


def test_two_acceptances_of_one_deposit_give_one_strain(
    *,
    lab: Lab,
    curator: User,
    manager: User,
    exempli: Taxon,
    make_deposit: MakeDeposit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deposit = make_deposit("checking")

    def accept(actor: User) -> tuple[User, Callable[[], object]]:
        return actor, lambda: services.deposit_accept(
            access=access_for(actor), deposit=deposit, facts=facts(exempli)
        )

    outcomes = race(monkeypatch, [accept(curator), accept(manager)])
    assert sorted(outcomes) == ["deposit_state", "done"]
    deposit.refresh_from_db()
    assert deposit.status == DepositStatus.ACCEPTED
    assert Strain.objects.filter(lab=lab).count() == 1
    assert StrainCounter.objects.get(lab=lab).last_seq == 1
    assert Passage.objects.filter(source_deposit=deposit).count() == 1
    assert AuditEvent.objects.filter(event_type="deposit_accepted").count() == 1


def test_an_acceptance_and_a_rejection_at_once_decide_once(
    *,
    lab: Lab,
    curator: User,
    manager: User,
    exempli: Taxon,
    make_deposit: MakeDeposit,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deposit = make_deposit("checking")
    outcomes = race(
        monkeypatch,
        [
            (
                curator,
                lambda: services.deposit_accept(
                    access=access_for(curator), deposit=deposit, facts=facts(exempli)
                ),
            ),
            (
                manager,
                lambda: services.deposit_reject(
                    access=access_for(manager), deposit=deposit, reason="mixed culture"
                ),
            ),
        ],
    )
    assert sorted(outcomes) == ["deposit_state", "done"]
    decided = Deposit.objects.get(pk=deposit.pk)
    assert decided.status in (DepositStatus.ACCEPTED, DepositStatus.REJECTED)
    assert Strain.objects.filter(lab=lab).count() == (decided.status == DepositStatus.ACCEPTED)

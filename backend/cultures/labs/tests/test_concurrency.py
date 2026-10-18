"""Two changes that would each leave the last active manager run at the same moment.

Real threads and real transactions, each thread with its own connection and
audit context. Two points are forced:
- the threads meet at the lab lock (the first _lock_lab call of each thread),
  so both are proven to arrive there with every check still ahead of them.
- the first thread past the manager check (_keep_a_manager) waits a moment
  for the other one. With the lab lock the other one cannot get there before
  the first commits, so the wait times out and the second thread then sees
  the committed change and is refused. Without the lock both pass the check
  and both commit: the lab is left without an active manager, and the
  assertions fail every time, not only when the timing is unlucky.
"""

import contextlib
import threading
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel
from cultures.labs import services
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.services import LastManager
from cultures.users.models import User
from cultures.users.services import user_deactivate

from .conftest import member_of, membership

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow]
REASON = "left the institute"
AFTER_CHECK_WAIT = 1.5  # seconds the first thread past the check waits for the other one

Call = Callable[[], object]


def race(
    monkeypatch: pytest.MonkeyPatch,
    first: tuple[User | None, Call],
    second: tuple[User | None, Call],
) -> list[str]:
    """Run both calls in threads with the two meeting points above. Returns their outcomes."""
    at_lock = threading.Barrier(2, timeout=5)
    after_check = threading.Barrier(2, timeout=AFTER_CHECK_WAIT)
    seen = threading.local()
    lock_lab: Callable[[int], Lab] = services._lock_lab
    keep_a_manager: Callable[..., None] = services._keep_a_manager

    def meet_at_lock(lab_id: int) -> Lab:
        if not getattr(seen, "lock", False):
            seen.lock = True
            _wait(at_lock)
        return lock_lab(lab_id)

    def wait_after_check(*args: Any, **kwargs: Any) -> None:
        keep_a_manager(*args, **kwargs)
        if not getattr(seen, "check", False):
            seen.check = True
            _wait(after_check)

    monkeypatch.setattr(services, "_lock_lab", meet_at_lock)
    monkeypatch.setattr(services, "_keep_a_manager", wait_after_check)
    outcomes: dict[int, str] = {}

    def run(index: int, actor: User | None, call: Call) -> None:
        try:
            with audit_context(
                channel=Channel.COMMAND,
                actor=actor,
                actor_kind=ActorKind.USER if actor else ActorKind.SYSTEM,
                actor_label="" if actor else "command:race",
                reason=REASON,
            ):
                call()
            outcomes[index] = "done"
        except LastManager as error:
            outcomes[index] = error.code
        finally:
            connection.close()

    threads = [
        threading.Thread(target=run, args=(i, actor, call))
        for i, (actor, call) in enumerate((first, second))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return [outcomes.get(i, "no outcome") for i in range(2)]


def _wait(barrier: threading.Barrier) -> None:
    """Meet the other thread if it comes. Go on alone when it cannot (it waits for our lock)."""
    with contextlib.suppress(threading.BrokenBarrierError):
        barrier.wait()


def active_managers(lab: Lab) -> int:
    return Membership.objects.filter(lab=lab, role=Role.MANAGER, user__is_active=True).count()


@pytest.fixture
def pair(lab: Lab) -> tuple[User, User]:
    """The lab's only two managers."""
    return member_of(lab, Role.MANAGER, "first"), member_of(lab, Role.MANAGER, "second")


def test_two_managers_stepping_down_through_the_api_leave_one_manager(
    lab: Lab, pair: tuple[User, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    def step_down(actor: User) -> tuple[User, Call]:
        return actor, lambda: services.member_change_role(
            access=access_for(actor), membership=membership(actor, lab), role=Role.VIEWER
        )

    outcomes = race(monkeypatch, step_down(pair[0]), step_down(pair[1]))
    assert sorted(outcomes) == ["done", "last_manager"]
    assert active_managers(lab) == 1
    assert AuditEvent.objects.filter(event_type="member_role_changed").count() == 1


def test_two_demotions_by_staff_leave_one_manager(
    lab: Lab, pair: tuple[User, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    def demote(user: User) -> tuple[None, Call]:
        return None, lambda: services.membership_set_role(
            membership=membership(user, lab), role=Role.VIEWER
        )

    outcomes = race(monkeypatch, demote(pair[0]), demote(pair[1]))
    assert sorted(outcomes) == ["done", "last_manager"]
    assert active_managers(lab) == 1
    assert AuditEvent.objects.filter(event_type="member_role_changed").count() == 1


def test_two_removals_by_staff_leave_one_manager(
    lab: Lab, pair: tuple[User, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    def remove(user: User) -> tuple[None, Call]:
        return None, lambda: services.membership_delete(membership=membership(user, lab))

    outcomes = race(monkeypatch, remove(pair[0]), remove(pair[1]))
    assert sorted(outcomes) == ["done", "last_manager"]
    assert active_managers(lab) == 1
    assert AuditEvent.objects.filter(event_type="member_removed").count() == 1


def test_a_deactivation_and_a_demotion_leave_one_active_manager(
    lab: Lab, pair: tuple[User, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    leaving, stepping_down = pair
    deactivate: tuple[None, Call] = (None, lambda: user_deactivate(user=leaving, reason=REASON))
    demote: tuple[None, Call] = (
        None,
        lambda: services.membership_set_role(
            membership=membership(stepping_down, lab), role=Role.VIEWER
        ),
    )
    outcomes = race(monkeypatch, deactivate, demote)
    assert sorted(outcomes) == ["done", "last_manager"]
    assert active_managers(lab) == 1
    events = AuditEvent.objects.filter(event_type__in=["user_deactivated", "member_role_changed"])
    assert events.count() == 1

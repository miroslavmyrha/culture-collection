"""The collection keeps an active superuser (#225): no path takes the last one away.

Erasure refused it before (test_erase.py). Deactivating one user, deactivating many and taking
the flag refuse it too, in the services and in the admin form, and two of them racing for the
last two superusers leave one.
"""

import contextlib
import threading
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection
from django.test import Client

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel
from cultures.users import services
from cultures.users.models import User

from .conftest import make_user, trail
from .test_admin import post_change

REASON = "left the institute"
REFUSED = services.LastSuperuser.default_detail

PATHS: dict[str, Callable[[User], object]] = {
    "deactivate": lambda u: services.user_deactivate(user=u, reason=REASON),
    "deactivate many": lambda u: services.users_deactivate(users=[u], reason=REASON),
    "take the flag": lambda u: services.user_set_superuser(
        user=u, is_superuser=False, reason=REASON
    ),
}


def flags(*users: User) -> list[tuple[bool, bool]]:
    return [
        (u.is_active, u.is_superuser)
        for u in User.objects.filter(pk__in=[u.pk for u in users]).order_by("pk")
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_the_last_active_superuser_is_kept(path: str, staff: User) -> None:
    """staff is the only active superuser; an inactive one does not count."""
    make_user("retired", is_superuser=True, is_active=False)
    with audit_context(channel=Channel.COMMAND, actor=staff):
        before = (flags(staff), trail())
        with pytest.raises(services.LastSuperuser) as refused:
            PATHS[path](staff)
    assert refused.value.code == "last_superuser"
    assert (flags(staff), trail()) == before


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_a_superuser_goes_when_another_active_one_remains(path: str, staff: User) -> None:
    other = make_user("other", is_superuser=True)
    with audit_context(channel=Channel.COMMAND, actor=staff):
        PATHS[path](other)
    assert flags(other) != [(True, True)]
    assert flags(staff) == [(True, True)]


@pytest.mark.django_db
def test_an_inactive_superuser_loses_the_flag_as_it_takes_no_active_one_away(member: User) -> None:
    retired = make_user("retired", is_superuser=True, is_active=False)
    with audit_context(channel=Channel.COMMAND, actor=member):
        services.user_set_superuser(user=retired, is_superuser=False, reason=REASON)
    assert flags(retired) == [(False, False)]


@pytest.mark.django_db
def test_deactivating_the_last_two_together_is_refused_whole(staff: User) -> None:
    other = make_user("other", is_superuser=True)
    with audit_context(channel=Channel.COMMAND, actor=staff):
        before = (flags(staff, other), trail())
        with pytest.raises(services.LastSuperuser):
            services.users_deactivate(users=[staff, other], reason=REASON)
    assert (flags(staff, other), trail()) == before


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["is_active", "is_superuser"])
def test_the_admin_form_says_why_on_the_field(
    field: str, admin_client: Client, staff: User
) -> None:
    before = (flags(staff), trail())
    unticked: dict[str, Any] = {field: False}
    response = post_change(admin_client, staff, reason=REASON, **unticked)
    assert response.status_code == 200
    errors = response.context["adminform"].form.errors
    assert errors[field] == [REFUSED]
    assert (flags(staff), trail()) == before


AFTER_CHECK_WAIT = 1.5  # seconds the first thread past the check waits for the other one


def _wait(barrier: threading.Barrier) -> None:
    """Meet the other thread if it comes. Go on alone when it cannot (it waits for our lock)."""
    with contextlib.suppress(threading.BrokenBarrierError):
        barrier.wait()


@pytest.mark.django_db(transaction=True)
@pytest.mark.slow
@pytest.mark.parametrize(
    ("first", "second"), [("deactivate", "deactivate"), ("deactivate", "take the flag")]
)
def test_two_racing_for_the_last_two_superusers_leave_one(
    first: str, second: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The threads meet at the lock with every check ahead of them, and the first past the check
    waits for the other. With the one lock the other cannot get there before the first commits,
    and then sees it and is refused. Without it both pass and both commit, every time."""
    pair = make_user("first", is_superuser=True), make_user("second", is_superuser=True)
    at_lock = threading.Barrier(2, timeout=5)
    after_check = threading.Barrier(2, timeout=AFTER_CHECK_WAIT)
    seen = threading.local()
    lock: Callable[..., Any] = services._lock_with_superusers
    keep: Callable[..., None] = services._keep_a_superuser

    def meet_at_lock(*args: Any) -> Any:
        if not getattr(seen, "lock", False):
            seen.lock = True
            _wait(at_lock)
        return lock(*args)

    def wait_after_check(*args: Any) -> None:
        keep(*args)
        if not getattr(seen, "check", False):
            seen.check = True
            _wait(after_check)

    monkeypatch.setattr(services, "_lock_with_superusers", meet_at_lock)
    monkeypatch.setattr(services, "_keep_a_superuser", wait_after_check)
    outcomes: dict[int, str] = {}

    def run(index: int, path: str, user: User) -> None:
        try:
            with audit_context(
                channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label="command:race",
                reason=REASON,
            ):  # fmt: skip
                PATHS[path](user)
            outcomes[index] = "done"
        except services.LastSuperuser as error:
            outcomes[index] = error.code
        finally:
            connection.close()

    threads = [
        threading.Thread(target=run, args=(i, path, user))
        for i, (path, user) in enumerate(((first, pair[0]), (second, pair[1])))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes.get(i, "no outcome") for i in range(2)) == ["done", "last_superuser"]
    assert User.objects.filter(is_superuser=True, is_active=True).count() == 1
    assert (
        AuditEvent.objects.filter(
            event_type__in=["user_deactivated", "user_superuser_changed"]
        ).count()
        == 1
    )

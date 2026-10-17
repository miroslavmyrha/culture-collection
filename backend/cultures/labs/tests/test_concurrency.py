"""The only two managers step down at the same moment: the lab keeps a manager.

Real threads and real transactions. The barrier sits at the lab lock (the first
_lock_lab call of each thread), so both threads are proven to meet there with
both checks still ahead of them. The lab lock serialises them: the second one
sees the first one's committed demotion and is refused as the last manager.
"""

import threading
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.labs import services
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.labs.services import LastManager
from cultures.users.models import User

from .conftest import member_of, membership

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow]


def test_two_managers_stepping_down_together_leave_one_manager(
    lab: Lab, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = member_of(lab, Role.MANAGER, "first"), member_of(lab, Role.MANAGER, "second")
    barrier = threading.Barrier(2, timeout=10)
    waited = threading.local()
    original: Callable[[int], Lab] = services._lock_lab

    def lock_after_meeting(lab_id: int) -> Lab:
        if not getattr(waited, "done", False):
            waited.done = True
            barrier.wait()
        return original(lab_id)

    monkeypatch.setattr(services, "_lock_lab", lock_after_meeting)
    results: dict[str, Any] = {}

    def step_down(actor: User) -> None:
        try:
            with audit_context(channel=Channel.API, actor=actor):
                services.member_change_role(
                    access=access_for(actor), membership=membership(actor, lab), role=Role.VIEWER
                )
            results[actor.username] = "demoted"
        except LastManager as error:
            results[actor.username] = error.code
        finally:
            connection.close()

    threads = [
        threading.Thread(target=step_down, args=(first,)),
        threading.Thread(target=step_down, args=(second,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results.values()) == ["demoted", "last_manager"]
    roles = sorted([membership(first, lab).role, membership(second, lab).role])
    assert roles == [Role.MANAGER, Role.VIEWER]
    assert AuditEvent.objects.filter(event_type="member_role_changed").count() == 1

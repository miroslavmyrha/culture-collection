"""Two placements into one position: exactly one wins.

The thread race runs two real transactions through the service at once: the lab lock makes
the second wait and then see the first's placement. The injected race puts a competing
insert right before the service's own, past every lock, so the partial unique index alone
decides, and the service turns its violation into the same answer.
"""

import threading

import pytest
from django.db import connection
from django.utils import timezone

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.core.testing import run_before
from cultures.labs.access import access_for
from cultures.lineage import services
from cultures.lineage.models import Passage, Vial, VialPlacement
from cultures.storage.tests.conftest import Tree
from cultures.users.models import User

from .support import MakeBatch, vials_of

pytestmark = pytest.mark.django_db


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_two_placements_into_one_position_one_wins(
    technician: User, curator: User, passage0: Passage, make_batch: MakeBatch, tree: Tree
) -> None:
    first, second = vials_of(make_batch(passage0, vial_count=2))
    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}

    def place(name: str, actor: User, vial: Vial) -> None:
        try:
            with audit_context(channel=Channel.API, actor=actor, request_id=f"req-{name}"):
                barrier.wait(timeout=5)
                services.vial_place(access=access_for(actor), vial=vial, box=tree.box, row=3, col=3)
            outcomes[name] = "placed"
        except services.PositionTaken:
            outcomes[name] = "taken"
        finally:
            connection.close()

    threads = [
        threading.Thread(target=place, args=("a", technician, first)),
        threading.Thread(target=place, args=("b", curator, second)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes.values()) == ["placed", "taken"]
    (placement,) = VialPlacement.objects.filter(box=tree.box, row=3, col=3)
    assert placement.removed_at is None
    assert AuditEvent.objects.filter(event_type="vial_placed").count() == 1


def test_the_index_decides_when_a_writer_skipped_the_locks(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    passage0: Passage,
    make_batch: MakeBatch,
    tree: Tree,
) -> None:
    first, second = vials_of(make_batch(passage0, vial_count=2))

    def competitor() -> None:
        VialPlacement.objects.create(
            lab_id=second.lab_id,
            vial=second,
            box=tree.box,
            row=3,
            col=3,
            placed_at=timezone.now(),
            placed_by=curator,
        )

    events = AuditEvent.objects.count()
    with run_before(services, "_save", competitor), pytest.raises(services.PositionTaken):
        services.vial_place(access=access_for(technician), vial=first, box=tree.box, row=3, col=3)
    assert VialPlacement.objects.filter(vial=first).count() == 0
    assert AuditEvent.objects.count() == events

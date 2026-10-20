"""The batch's states (ADR 0008, D16, amendment of 2026-10-20), edge by edge: all 16 pairs
through the service's one edge checker and through the trigger, against
lineage.models.BATCH_EDGES, and the public release and hold from every state. Neither may
allow a pair the other refuses."""

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.labs.access import access_for
from cultures.lineage import services
from cultures.lineage.models import BATCH_EDGES, Batch, BatchStatus, Passage
from cultures.users.models import User

from .support import MakeBatch, pass_all

pytestmark = pytest.mark.django_db
STATES = sorted(BatchStatus)
# How to reach each state from pending_check along allowed edges.
PATHS: dict[str, list[str]] = {
    "pending_check": [],
    "released": ["released"],
    "on_hold": ["on_hold"],
    "exhausted": ["exhausted"],
}


def test_every_state_has_a_path() -> None:
    assert sorted(PATHS) == sorted(BatchStatus.values)
    assert sorted(BATCH_EDGES) == STATES


def update(batch: Batch, status: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE lineage_batch SET status = %s, status_reason = 'test',"
            " status_changed_at = now() WHERE id = %s",
            [status, batch.pk],
        )


def put(batch: Batch, status: str) -> Batch:
    """Into the state along allowed edges, past the service (no event)."""
    for step in PATHS[status]:
        update(batch, step)
    return Batch.objects.get(pk=batch.pk)


def allowed(old: BatchStatus, new: BatchStatus) -> bool:
    return new == old or new in BATCH_EDGES[old]


@pytest.fixture
def passed(
    as_technician: AuditContext, technician: User, passage0: Passage, make_batch: MakeBatch
) -> list[Batch]:
    """One batch per state, each with passed checks of all three kinds: the release rule never
    stands in the way, so only the edges decide."""
    batches = [make_batch(passage0, vial_count=1) for _ in STATES]
    for batch in batches:
        pass_all(technician, batch)
    return batches


@pytest.mark.parametrize("old", STATES)
def test_the_trigger_allows_exactly_the_edges(passed: list[Batch], old: BatchStatus) -> None:
    for made, new in zip(passed, STATES, strict=True):
        batch = put(made, old)
        try:
            with transaction.atomic():
                update(batch, new)
            done = True
        except (IntegrityError, InternalError) as error:
            assert "a batch cannot go from" in str(error), error
            done = False
        assert done == allowed(old, new), (old, new)


@pytest.mark.parametrize("old", STATES)
def test_the_service_allows_exactly_the_edges(
    passed: list[Batch], as_technician: AuditContext, old: BatchStatus
) -> None:
    """_move_batch is the one edge check every status change of a service goes through."""
    for batch, new in zip(passed, STATES, strict=True):
        locked = put(batch, old)
        events = AuditEvent.objects.count()
        if new == old:
            continue  # the public services return early for the same state, tested below
        try:
            with transaction.atomic():
                services._move_batch(locked, new, "test")
            done = True
        except services.BatchEdgeNotAllowed as error:
            assert error.code == "transition_not_allowed"
            done = False
        assert done == allowed(old, new), (old, new)
        assert Batch.objects.get(pk=batch.pk).status == (new if done else old)
        assert AuditEvent.objects.count() == events + (1 if done else 0)


@pytest.mark.parametrize("old", STATES)
def test_release_and_hold_from_every_state(
    passed: list[Batch], curator: User, old: BatchStatus
) -> None:
    access = access_for(curator)
    release, hold = passed[0], passed[1]
    expected = {
        "pending_check": (BatchStatus.RELEASED, BatchStatus.ON_HOLD),
        "released": (BatchStatus.RELEASED, BatchStatus.ON_HOLD),
        "on_hold": (BatchStatus.RELEASED, BatchStatus.ON_HOLD),
        "exhausted": (None, None),
    }[old]
    with audit_context(channel=Channel.API, actor=curator, request_id="req-c"):
        for made, decide, target in (
            (release, services.batch_release, expected[0]),
            (hold, services.batch_hold, expected[1]),
        ):
            batch = put(made, old)
            if target is None:
                with pytest.raises(services.BatchExhausted):
                    decide(access=access, batch=batch, reason="decided")
                assert Batch.objects.get(pk=batch.pk).status == old
            else:
                assert decide(access=access, batch=batch, reason="decided").status == target

"""The vial's states (ADR 0008, D7), edge by edge: all 81 pairs through the service and through
the trigger, against lineage.models.EDGES. Neither may allow a pair the other refuses."""

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent
from cultures.labs.access import Access, access_for
from cultures.lineage import services
from cultures.lineage.models import EDGES, Passage, Vial, VialStatus
from cultures.lineage.services import MANUAL_TARGETS
from cultures.users.models import User

from .support import MakeBatch, vials_of
from .test_constraints import PATHS

pytestmark = pytest.mark.django_db
STATES = sorted(VialStatus)


def put(vial: Vial, status: str) -> Vial:
    """Into the state along allowed edges, past the service (no event)."""
    with connection.cursor() as cursor:
        for step in PATHS[status]:
            cursor.execute(
                "UPDATE lineage_vial SET status = %s, status_changed_at = now() WHERE id = %s",
                [step, vial.pk],
            )
    return Vial.objects.get(pk=vial.pk)


def allowed(old: VialStatus, new: VialStatus) -> bool:
    return new == old or new in EDGES[old]


@pytest.mark.parametrize("old", STATES)
def test_the_trigger_allows_exactly_the_edges(
    passage0: Passage, make_batch: MakeBatch, old: VialStatus
) -> None:
    vials = [put(v, old) for v in vials_of(make_batch(passage0, vial_count=len(STATES)))]
    for vial, new in zip(vials, STATES, strict=True):
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE lineage_vial SET status = %s, status_changed_at = now() WHERE id = %s",
                    [new, vial.pk],
                )
            done = True
        except (IntegrityError, InternalError) as error:
            assert "a vial cannot go from" in str(error), error
            done = False
        assert done == allowed(old, new), (old, new)


@pytest.mark.parametrize("old", STATES)
def test_the_service_allows_exactly_the_edges_a_person_may_take(
    passage0: Passage,
    make_batch: MakeBatch,
    as_technician: AuditContext,
    technician: User,
    old: VialStatus,
) -> None:
    access: Access = access_for(technician)
    vials = [put(v, old) for v in vials_of(make_batch(passage0, vial_count=len(STATES)))]
    for vial, new in zip(vials, STATES, strict=True):
        events = AuditEvent.objects.count()
        try:
            services.vial_transition(access=access, vial=vial, status=new, reason="test")
            done = True
        except services.EdgeNotAllowed as error:
            assert error.code == "transition_not_allowed", (old, new)
            done = False
        # Reserved and distributed are distribution's (#18), also as the same state again.
        expected = allowed(old, new) and new in MANUAL_TARGETS
        assert done == expected, (old, new)
        assert Vial.objects.get(pk=vial.pk).status == (new if done else old)
        moved = done and new != old
        assert AuditEvent.objects.count() == events + (1 if moved else 0), (old, new)


def test_a_vial_with_a_history_is_not_entered_in_error(
    passage0: Passage, make_batch: MakeBatch, as_technician: AuditContext, technician: User
) -> None:
    access = access_for(technician)
    vial = vials_of(make_batch(passage0, vial_count=1))[0]
    services.vial_transition(access=access, vial=vial, status=VialStatus.LOST, reason="not found")
    services.vial_transition(access=access, vial=vial, status=VialStatus.AVAILABLE, reason="found")
    with pytest.raises(services.EdgeNotAllowed) as raised:
        services.vial_transition(
            access=access, vial=vial, status=VialStatus.ENTERED_IN_ERROR, reason="typo"
        )
    assert raised.value.code == "vial_has_history"
    with (
        pytest.raises((IntegrityError, InternalError), match="whose status never changed"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE lineage_vial SET status = 'entered_in_error' WHERE id = %s", [vial.pk]
        )

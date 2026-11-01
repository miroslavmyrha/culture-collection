"""The vial's states (ADR 0008, D7), edge by edge: all 81 pairs through the service and through
the trigger, for a strain in the collection, one deaccessioned with its material destroyed and
one deaccessioned with its material kept (#150), against lineage.models.vial_edges. Neither may
allow a pair the other refuses."""

from collections.abc import Callable

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent
from cultures.labs.access import Access, access_for
from cultures.lineage import services
from cultures.lineage.models import (
    EDGES,
    EDGES_MATERIAL_DESTROYED,
    Passage,
    Vial,
    VialStatus,
    material_destroyed,
    vial_edges,
)
from cultures.lineage.services import MANUAL_TARGETS
from cultures.strains.models import FinalUse, Strain
from cultures.users.models import User

from .support import MakeBatch, deaccession, deaccessioned_past_the_service, vials_of
from .test_constraints import PATHS

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("vial_edges_alone")]
STATES = sorted(VialStatus)
S = VialStatus
# The strain of the vials: in the collection, deaccessioned with no final use (its material
# destroyed, strains.services._leave), or a quarantine pest deaccessioned for storage (kept).
KINDS = ["in_collection", "material_destroyed", "material_kept"]
Vials = Callable[[VialStatus], tuple[Strain, list[Vial]]]


def put(vial: Vial, status: str) -> Vial:
    """Into the state along allowed edges, past the service (no event)."""
    with connection.cursor() as cursor:
        for step in PATHS[status]:
            cursor.execute(
                "UPDATE lineage_vial SET status = %s, status_changed_at = now() WHERE id = %s",
                [step, vial.pk],
            )
    return Vial.objects.get(pk=vial.pk)


@pytest.fixture
def vials_in(
    *,
    request: pytest.FixtureRequest,
    strain: Strain,
    passage0: Passage,
    quarantine_pest: Strain,
    make_batch: MakeBatch,
    curator: User,
    manager: User,
) -> Vials:
    """One vial per state, all in `old`, of a strain of the kind the test names. The material
    destroyed: the strain's row as a deaccession leaves it, past the service after the vials
    took their state (the service would mark them to destroy). The material kept: deaccessioned
    through the services first, then the vials take their state along the edges it keeps."""
    kind: str = request.param

    def make(old: VialStatus) -> tuple[Strain, list[Vial]]:
        if kind == "material_kept":
            batch = make_batch(Passage.objects.get(strain=quarantine_pest, number=0), vial_count=9)
            deaccession(quarantine_pest, FinalUse.STORAGE, proposer=curator, confirmer=manager)
            owner = quarantine_pest
        else:
            batch = make_batch(passage0, vial_count=9)
            owner = strain
        vials = [put(v, old) for v in vials_of(batch)]
        if kind == "material_destroyed":
            deaccessioned_past_the_service(strain, curator)
        owner.refresh_from_db()
        assert material_destroyed(owner) == (kind == "material_destroyed")
        return owner, vials

    return make


def allowed(strain: Strain, old: VialStatus, new: VialStatus) -> bool:
    return new == old or new in vial_edges(strain)[old]


def refused_for_the_strain(strain: Strain, old: VialStatus, new: VialStatus) -> bool:
    """An edge of a vial in the collection that this strain's material no longer takes."""
    return new in EDGES[old] and not allowed(strain, old, new)


def test_a_strain_whose_material_was_destroyed_sends_its_vials_only_to_destruction() -> None:
    """The table on its own, written out: what the trigger and the service are compared with."""
    written = {
        S.AVAILABLE: {S.CONSUMED, S.TO_DESTROY, S.LOST, S.ENTERED_IN_ERROR},
        S.RESERVED: {S.DISTRIBUTED, S.TO_DESTROY},
        S.QUARANTINED: {S.TO_DESTROY},
        S.TO_DESTROY: {S.DESTROYED},
        S.LOST: {S.TO_DESTROY},
        S.CONSUMED: set(),
        S.DESTROYED: set(),
        S.DISTRIBUTED: set(),
        S.ENTERED_IN_ERROR: set(),
    }
    assert written == EDGES_MATERIAL_DESTROYED
    assert EDGES[S.LOST] == {S.AVAILABLE}


@pytest.mark.parametrize("vials_in", KINDS, indirect=True)
@pytest.mark.parametrize("old", STATES)
def test_the_trigger_allows_exactly_the_edges(vials_in: Vials, old: VialStatus) -> None:
    strain, vials = vials_in(old)
    for vial, new in zip(vials, STATES, strict=True):
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE lineage_vial SET status = %s, status_changed_at = now() WHERE id = %s",
                    [new, vial.pk],
                )
            done = True
        except (IntegrityError, InternalError) as error:
            expected = (
                "deaccessioned with its material destroyed"
                if refused_for_the_strain(strain, old, new)
                else "a vial cannot go from"
            )
            assert expected in str(error), (old, new, error)
            done = False
        assert done == allowed(strain, old, new), (old, new)


@pytest.mark.parametrize("vials_in", KINDS, indirect=True)
@pytest.mark.parametrize("old", STATES)
def test_the_service_allows_exactly_the_edges_a_person_may_take(
    vials_in: Vials, as_technician: AuditContext, technician: User, old: VialStatus
) -> None:
    access: Access = access_for(technician)
    strain, vials = vials_in(old)
    for vial, new in zip(vials, STATES, strict=True):
        events = AuditEvent.objects.count()
        try:
            services.vial_transition(access=access, vial=vial, status=new, reason="test")
            done = True
        except services.EdgeNotAllowed as error:
            expected = (
                "strain_material_destroyed"
                if new in MANUAL_TARGETS and refused_for_the_strain(strain, old, new)
                else "transition_not_allowed"
            )
            assert error.code == expected, (old, new)
            done = False
        except services.VialReserved:
            done = False
        # Reserved and distributed are distribution's (#18), also as the same state again, and
        # a reserved vial leaves its state only through its request.
        expected_done = (
            allowed(strain, old, new) and new in MANUAL_TARGETS and old != VialStatus.RESERVED
        )
        assert done == expected_done, (old, new)
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

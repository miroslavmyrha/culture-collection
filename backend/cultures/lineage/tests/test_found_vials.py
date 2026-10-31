"""A vial lost when its strain was deaccessioned, found later (#150, ADR 0008 amendment of
2026-10-31). The deaccession marked the strain's held vials to destroy and left the lost one
lost. Found, it goes to destruction when the deaccession destroyed the material, and is
available as before when the final use kept it (collection, storage). Every pair of states for
each kind of strain: test_vial_states.py."""

import pytest
from django.db import DatabaseError, connection, transaction

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.core.testing import assert_problem, logged_in
from cultures.labs.access import access_for
from cultures.lineage import services
from cultures.lineage.models import Passage, Vial, VialPlacement, VialStatus
from cultures.storage.tests.conftest import Tree
from cultures.strains.models import FinalUse, Strain
from cultures.users.models import User

from .support import VIALS_URL, MakeBatch, deaccession, vials_of

pytestmark = pytest.mark.django_db
S = VialStatus
# No final use (a strain that is not a quarantine pest) and destruction destroy the material;
# collection and storage keep it (strains.models.KEEPS_MATERIAL).
DESTROYING = [None, FinalUse.DESTRUCTION]
KEEPING = [FinalUse.COLLECTION, FinalUse.STORAGE]


@pytest.fixture
def found(
    *,
    request: pytest.FixtureRequest,
    make_batch: MakeBatch,
    technician: User,
    curator: User,
    manager: User,
    tree: Tree,
) -> tuple[Strain, Vial, Vial]:
    """Two vials of a strain in a box, one lost, then the strain deaccessioned with the final use
    the test names: (the strain, the lost vial, the other one)."""
    final_use: FinalUse | None = request.param
    strain: Strain = request.getfixturevalue("strain" if final_use is None else "quarantine_pest")
    batch = make_batch(Passage.objects.get(strain=strain, number=0), vial_count=2, box=tree.box)
    lost, held = vials_of(batch)
    with audit_context(channel=Channel.API, actor=technician, request_id="req-setup"):
        services.vial_transition(
            access=access_for(technician), vial=lost, status=S.LOST, reason="Not in its box."
        )
    deaccession(strain, final_use, proposer=curator, confirmer=manager)
    lost.refresh_from_db()
    held.refresh_from_db()
    return strain, lost, held


def transition(user: User, vial: Vial, status: VialStatus, reason: str) -> Vial:
    with audit_context(channel=Channel.API, actor=user, request_id="req-found"):
        return services.vial_transition(
            access=access_for(user), vial=vial, status=status, reason=reason
        )


@pytest.mark.parametrize("found", DESTROYING, indirect=True)
def test_a_found_vial_of_a_strain_whose_material_was_destroyed_goes_to_destruction(
    found: tuple[Strain, Vial, Vial], technician: User
) -> None:
    strain, lost, held = found
    # What the deaccession did: the vial in the box to destroy, the lost one left lost.
    assert (lost.status, held.status) == (S.LOST, S.TO_DESTROY)
    transition(technician, lost, S.TO_DESTROY, "Found behind the rack.")
    vial = Vial.objects.get(pk=lost.pk)
    assert vial.status == S.TO_DESTROY
    event = AuditEvent.objects.order_by("-pk").first()
    assert event is not None
    assert (event.event_type, event.subject_id, event.reason) == (
        "vial_status_changed",
        vial.public_id,
        "Found behind the rack.",
    )
    assert event.changes == {"status": ["lost", "to_destroy"]}
    assert event.strain_id == strain.public_id
    # Found, it is in no box: it waits for destruction where it was found.
    assert not VialPlacement.objects.filter(vial=vial, removed_at__isnull=True).exists()


@pytest.mark.parametrize("found", DESTROYING, indirect=True)
def test_such_a_vial_is_never_available_again(
    found: tuple[Strain, Vial, Vial], technician: User
) -> None:
    _, lost, _ = found
    events = AuditEvent.objects.count()
    with pytest.raises(services.MaterialDestroyed) as raised:
        transition(technician, lost, S.AVAILABLE, "Found behind the rack.")
    assert (raised.value.code, raised.value.attr) == ("strain_material_destroyed", "status")
    assert "Mark a found vial to destroy." in str(raised.value.detail)
    assert Vial.objects.get(pk=lost.pk).status == S.LOST
    assert AuditEvent.objects.count() == events
    # Nor past the service: the vial trigger reads the strain too.
    for status, refusal in (
        (S.AVAILABLE, "deaccessioned with its material destroyed"),
        (S.RESERVED, "a vial cannot go from lost to reserved"),
        (S.QUARANTINED, "a vial cannot go from lost to quarantined"),
    ):
        with (
            pytest.raises(DatabaseError, match=refusal),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE lineage_vial SET status = %s, status_changed_at = now() WHERE id = %s",
                [status, lost.pk],
            )


@pytest.mark.parametrize("found", KEEPING, indirect=True)
def test_a_found_vial_of_a_strain_whose_material_was_kept_is_available_as_before(
    found: tuple[Strain, Vial, Vial], technician: User
) -> None:
    _, lost, held = found
    assert (lost.status, held.status) == (S.LOST, S.AVAILABLE)
    with pytest.raises(services.EdgeNotAllowed) as raised:
        transition(technician, lost, S.TO_DESTROY, "Found behind the rack.")
    assert raised.value.code == "transition_not_allowed"
    transition(technician, lost, S.AVAILABLE, "Found behind the rack.")
    assert Vial.objects.get(pk=lost.pk).status == S.AVAILABLE


@pytest.mark.parametrize("found", [None], indirect=True)
def test_the_api_names_the_refusal_on_the_status(
    found: tuple[Strain, Vial, Vial], technician: User
) -> None:
    _, lost, _ = found
    url = f"{VIALS_URL}{lost.public_id}/status/"
    client = logged_in(technician)
    assert_problem(
        client.post(
            url, {"status": "available", "reason": "found"}, content_type="application/json"
        ),
        400,
        "strain_material_destroyed",
        "status",
    )
    done = client.post(
        url, {"status": "to_destroy", "reason": "found"}, content_type="application/json"
    )
    assert (done.status_code, done.json()["status"]) == (200, "to_destroy")

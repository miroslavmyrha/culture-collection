"""What may be distributed (#17 for #18): an available vial of a released batch of distribution
stock, of a strain that still supplies. Never seed stock, never a batch pending its checks, on
hold or exhausted. The batch figure and the vial selector read one definition
(selectors.distributable), so they cannot disagree."""

import pytest
from django.db import connection

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import Channel
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.lineage import selectors, services
from cultures.lineage.models import Batch, BatchStatus, Passage, Purpose, Vial, VialStatus
from cultures.strains.models import Strain
from cultures.users.models import User

from .support import MakeBatch, deaccessioned_past_the_service, pass_all, vials_of

pytestmark = pytest.mark.django_db
REASON = "all three checks after preservation passed"


def released(technician: User, curator: User, batch: Batch) -> Batch:
    pass_all(technician, batch)
    with audit_context(channel=Channel.API, actor=curator, request_id="req-c"):
        return services.batch_release(access=access_for(curator), batch=batch, reason=REASON)


def distributable(viewer: User, lab: Lab) -> set[Vial]:
    return set(
        selectors.vials_for_distribution(access=access_for(viewer), lab=lab, perm=Perm.VIEW_STRAINS)
    )


def figures(viewer: User, lab: Lab) -> dict[int, int]:
    rows = selectors.batch_list(access=access_for(viewer), lab=lab)
    return {b.pk: vars(b)["vials_distributable"] for b in rows}


def test_only_available_vials_of_released_distribution_batches(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    viewer: User,
    lab: Lab,
    passage0: Passage,
    make_batch: MakeBatch,
) -> None:
    ready = released(technician, curator, make_batch(passage0, vial_count=3))
    seed = released(technician, curator, make_batch(passage0, vial_count=2, purpose=Purpose.SEED))
    pending = make_batch(passage0, vial_count=2)
    held = make_batch(passage0, vial_count=2)
    with audit_context(channel=Channel.API, actor=curator, request_id="req-c"):
        services.batch_hold(access=access_for(curator), batch=held, reason="a doubt")
    first, second, third = vials_of(ready)
    services.vial_transition(
        access=access_for(technician), vial=second, status=VialStatus.QUARANTINED, reason="crack"
    )
    assert Vial.objects.get(pk=first.pk).status == VialStatus.AVAILABLE
    assert distributable(viewer, lab) == {first, third}
    counts = figures(viewer, lab)
    assert counts == {ready.pk: 2, seed.pk: 0, pending.pk: 0, held.pk: 0}


def test_a_hold_or_an_exhausted_batch_takes_its_vials_off(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    viewer: User,
    lab: Lab,
    passage0: Passage,
    make_batch: MakeBatch,
) -> None:
    batch = released(technician, curator, make_batch(passage0, vial_count=2))
    assert len(distributable(viewer, lab)) == 2
    with audit_context(channel=Channel.API, actor=curator, request_id="req-c"):
        services.batch_hold(access=access_for(curator), batch=batch, reason="a complaint")
    assert distributable(viewer, lab) == set()
    with audit_context(channel=Channel.API, actor=curator, request_id="req-c"):
        services.batch_release(access=access_for(curator), batch=batch, reason=REASON)
    assert len(distributable(viewer, lab)) == 2
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE lineage_batch SET status = 'exhausted', status_reason = 'sent',"
            " status_changed_at = now() WHERE id = %s",
            [batch.pk],
        )
    assert distributable(viewer, lab) == set()
    assert figures(viewer, lab) == {batch.pk: 0}


def test_a_deaccessioned_strain_gives_nothing(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    viewer: User,
    lab: Lab,
    passage0: Passage,
    make_batch: MakeBatch,
    strain: Strain,
) -> None:
    """Past the service, which would mark the vials for destruction (#20): the selector alone
    leaves the strain out. A pending strain has no batch."""
    batch = released(technician, curator, make_batch(passage0, vial_count=2))
    deaccessioned_past_the_service(strain, curator)
    assert distributable(viewer, lab) == set()
    assert figures(viewer, lab) == {batch.pk: 0}


def test_the_selector_is_scoped_to_the_reader_and_the_lab(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    viewer: User,
    outsider: User,
    lab: Lab,
    other_lab: Lab,
    passage0: Passage,
    make_batch: MakeBatch,
) -> None:
    released(technician, curator, make_batch(passage0, vial_count=1))
    assert len(distributable(viewer, lab)) == 1
    assert distributable(outsider, lab) == set()
    assert distributable(viewer, other_lab) == set()
    assert (
        set(
            selectors.vials_for_distribution(
                access=access_for(viewer), lab=lab, perm=Perm.MANAGE_DISTRIBUTION
            )
        )
        == set()
    )  # a viewer may not distribute


def test_a_new_batch_is_pending_and_gives_nothing(
    viewer: User, lab: Lab, passage0: Passage, make_batch: MakeBatch
) -> None:
    batch = make_batch(passage0, vial_count=2)
    assert batch.status == BatchStatus.PENDING_CHECK
    assert distributable(viewer, lab) == set()

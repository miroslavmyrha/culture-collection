"""As the runtime role (ADR 0005): preserving, placing, moving and a state change work, deletes
do not, and the guard triggers hold for it as for everybody. Grants come from
audit.roles.APP_ROLE_GRANTS; audit/tests/test_roles.py compares every table with it, this
proves what the lineage tables need."""

import pytest
from django.db.backends.utils import CursorWrapper

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel, RowChange
from cultures.audit.tests.conftest import TEST_ROLES, refused
from cultures.labs.access import access_for
from cultures.lineage import services
from cultures.lineage.models import (
    Batch,
    BatchCheck,
    BatchStatus,
    CheckKind,
    CheckStatus,
    Passage,
    VialStatus,
)
from cultures.storage.tests.conftest import Tree
from cultures.strains.models import Strain
from cultures.users.models import User

from .support import deaccession, new_batch, new_check, open_place, record, vials_of

pytestmark = pytest.mark.django_db


def test_the_runtime_role_does_the_bench_work(
    as_technician: AuditContext,
    technician: User,
    passage0: Passage,
    tree: Tree,
    runtime_role: CursorWrapper,
) -> None:
    runtime_role.execute("SELECT current_user")
    assert runtime_role.fetchone() == (TEST_ROLES.runtime,)
    access = access_for(technician)
    batch = services.batch_preserve(
        access=access, passage=passage0, data=new_batch(vial_count=2, box=tree.box)
    )
    first, second = vials_of(batch)
    services.vial_place(access=access, vial=first, box=tree.box, row=5, col=5)
    services.vial_transition(access=access, vial=second, status=VialStatus.LOST, reason="gone")
    services.vial_revive(access=access, vial=first)
    assert open_place(first) is None
    assert AuditEvent.objects.filter(strain_id=passage0.strain.public_id).count() > 5
    labels = set(RowChange.objects.values_list("table_label", flat=True))
    assert {"lineage.batch", "lineage.vial", "lineage.vialplacement", "lineage.passage"} <= labels


def test_the_runtime_role_records_checks_and_releases(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    passage0: Passage,
    runtime_role: CursorWrapper,
) -> None:
    access = access_for(technician)
    batch = services.batch_preserve(access=access, passage=passage0, data=new_batch(vial_count=2))
    vial = vials_of(batch)[0]
    wrong = record(technician, batch, CheckKind.IDENTITY, vial=vial)
    services.check_record(
        access=access,
        batch=batch,
        data=new_check(CheckKind.IDENTITY, vial=vial),
        supersedes=wrong,
        reason="the wrong method was chosen",
    )
    record(technician, batch, CheckKind.PURITY, vial=vial)
    record(technician, batch, CheckKind.VIABILITY, vial=vial)
    with audit_context(channel=Channel.API, actor=curator, request_id="req-c"):
        services.batch_release(access=access_for(curator), batch=batch, reason="checks passed")
    assert Batch.objects.get(pk=batch.pk).status == BatchStatus.RELEASED
    assert BatchCheck.objects.filter(batch=batch, status=CheckStatus.VALID).count() == 3
    labels = set(RowChange.objects.values_list("table_label", flat=True))
    assert "lineage.batchcheck" in labels


def test_the_runtime_role_cannot_bring_back_a_vial_of_a_strain_whose_material_was_destroyed(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    manager: User,
    passage0: Passage,
    runtime_role: CursorWrapper,
) -> None:
    """#150: a vial lost at the deaccession, written past the services as the app's own role."""
    access = access_for(technician)
    batch = services.batch_preserve(access=access, passage=passage0, data=new_batch(vial_count=1))
    vial = vials_of(batch)[0]
    services.vial_transition(access=access, vial=vial, status=VialStatus.LOST, reason="gone")
    deaccession(passage0.strain, None, proposer=curator, confirmer=manager)
    refused(
        runtime_role,
        f"UPDATE lineage_vial SET status = 'available' WHERE id = {vial.pk}",  # noqa: S608 (a pk)
        "deaccessioned with its material destroyed",
    )
    runtime_role.execute(
        "UPDATE lineage_vial SET status = 'to_destroy' WHERE id = %s RETURNING status", [vial.pk]
    )
    assert runtime_role.fetchone() == ("to_destroy",)


@pytest.mark.rule("R-END-03")
def test_the_runtime_role_cannot_destroy_a_vial_of_a_regulated_strain(
    *,
    as_technician: AuditContext,
    technician: User,
    passage0: Passage,
    regulated: Strain,
    runtime_role: CursorWrapper,
) -> None:
    """#158, ADR 0009: written past the services as the app's own role, a regulated strain's
    vial to destroy stays so; a vial of a strain without restrictions is destroyed."""
    access = access_for(technician)
    vials = {}
    for strain, passage in (
        (regulated, Passage.objects.get(strain=regulated, number=0)),
        (passage0.strain, passage0),
    ):
        batch = services.batch_preserve(access=access, passage=passage, data=new_batch())
        vials[strain.pk] = vial = vials_of(batch)[0]
        services.vial_transition(
            access=access, vial=vial, status=VialStatus.TO_DESTROY, reason="tube cracked"
        )
    refused(
        runtime_role,
        f"UPDATE lineage_vial SET status = 'destroyed' WHERE id = {vials[regulated.pk].pk}",  # noqa: S608 (a pk)
        "a vial of a regulated strain is destroyed only with a destruction record",
    )
    runtime_role.execute(
        "UPDATE lineage_vial SET status = 'destroyed' WHERE id = %s RETURNING status",
        [vials[passage0.strain_id].pk],
    )
    assert runtime_role.fetchone() == ("destroyed",)


@pytest.mark.parametrize(
    "table",
    [
        "lineage_batch",
        "lineage_vial",
        "lineage_vialplacement",
        "lineage_passage",
        "lineage_batchcheck",
    ],
)
def test_the_runtime_role_deletes_nothing(
    *,
    as_technician: AuditContext,
    technician: User,
    passage0: Passage,
    tree: Tree,
    runtime_role: CursorWrapper,
    table: str,
) -> None:
    batch = services.batch_preserve(
        access=access_for(technician), passage=passage0, data=new_batch(box=tree.box)
    )
    record(technician, batch)
    refused(runtime_role, f"DELETE FROM {table}", "permission denied")  # noqa: S608 (a constant)

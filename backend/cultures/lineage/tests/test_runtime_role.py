"""As the runtime role (ADR 0005): preserving, placing, moving and a state change work, deletes
do not, and the guard triggers hold for it as for everybody. Grants come from
audit.roles.APP_ROLE_GRANTS; audit/tests/test_roles.py compares every table with it, this
proves what the lineage tables need."""

import pytest
from django.db.backends.utils import CursorWrapper

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent, RowChange
from cultures.audit.tests.conftest import TEST_ROLES, refused
from cultures.labs.access import access_for
from cultures.lineage import services
from cultures.lineage.models import Passage, VialStatus
from cultures.storage.tests.conftest import Tree
from cultures.users.models import User

from .support import new_batch, open_place, vials_of

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


@pytest.mark.parametrize(
    "table", ["lineage_batch", "lineage_vial", "lineage_vialplacement", "lineage_passage"]
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
    services.batch_preserve(
        access=access_for(technician), passage=passage0, data=new_batch(box=tree.box)
    )
    refused(runtime_role, f"DELETE FROM {table}", "permission denied")  # noqa: S608 (a constant)

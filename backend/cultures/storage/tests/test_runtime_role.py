"""As the runtime role (ADR 0005): the app builds, moves and retires units, the path trigger
and its cascade work with the role's own grants, deletes do not, and the guards hold for it as
for everybody. Grants come from audit.roles.APP_ROLE_GRANTS; test_roles.py compares every
table with it, this proves what the storage tables need."""

import pytest
from django.db.backends.utils import CursorWrapper

from cultures.audit.context import AuditContext
from cultures.audit.models import RowChange
from cultures.audit.tests.conftest import TEST_ROLES, refused
from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.storage import services
from cultures.storage.models import BoxType, StorageUnit, UnitKind, UnitStatus
from cultures.storage.services import NewUnit

pytestmark = pytest.mark.django_db


def build(
    access: Access, lab: Lab, box_type: BoxType
) -> tuple[StorageUnit, StorageUnit, StorageUnit]:
    def add(
        kind: UnitKind, name: str, parent: StorageUnit | None = None, **more: object
    ) -> StorageUnit:
        return services.unit_create(
            access=access,
            lab=lab,
            data=NewUnit(kind=kind, name=name, parent=parent, **more),  # type: ignore[arg-type]
        )

    freezer = add(UnitKind.FREEZER, "Freezer A", max_risk_group=2)
    rack = add(UnitKind.RACK, "Rack 1", freezer)
    box = add(UnitKind.BOX, "Box 1", rack, box_type=box_type)
    return freezer, rack, box


def test_the_runtime_role_builds_moves_and_retires_units(
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    box_9x9: BoxType,
    runtime_role: CursorWrapper,
) -> None:
    runtime_role.execute("SELECT current_user")
    assert runtime_role.fetchone() == (TEST_ROLES.runtime,)
    _, rack, box = build(curator_access, lab, box_9x9)
    tank = services.unit_create(
        access=curator_access,
        lab=lab,
        data=NewUnit(kind=UnitKind.LN2_TANK, name="Tank B", max_risk_group=2),
    )
    services.unit_move(access=curator_access, unit=rack, parent=tank, slot=2)
    assert list(StorageUnit.objects.get(pk=box.pk).path) == [tank.pk, rack.pk, box.pk]
    services.unit_set_status(
        access=curator_access, unit=box, status=UnitStatus.RETIRED, reason="cracked"
    )
    # The trigger wrote the row changes as the audit owner, though the runtime role may not.
    labels = set(RowChange.objects.values_list("table_label", flat=True))
    assert {"storage.storageunit", "storage.boxtype"} <= labels


@pytest.mark.parametrize("table", ["storage_storageunit", "storage_boxtype"])
def test_the_runtime_role_deletes_no_storage_row(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    box_9x9: BoxType,
    runtime_role: CursorWrapper,
    table: str,
) -> None:
    build(curator_access, lab, box_9x9)
    refused(runtime_role, f"DELETE FROM {table}", f"permission denied for table {table}")  # noqa: S608
    refused(runtime_role, f"TRUNCATE {table}", f"permission denied for table {table}")


def test_the_guards_hold_for_the_runtime_role(
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    box_9x9: BoxType,
    runtime_role: CursorWrapper,
) -> None:
    _, rack, box = build(curator_access, lab, box_9x9)
    refused(
        runtime_role,
        f"UPDATE storage_storageunit SET parent_id = {box.pk} WHERE id = {rack.pk}",  # noqa: S608
        "a unit cannot go inside itself or a unit it holds",
    )
    refused(runtime_role, "UPDATE storage_storageunit SET kind = 'box'", "a unit keeps its kind")
    refused(runtime_role, "UPDATE storage_boxtype SET rows = 3", "keeps its public id and its size")

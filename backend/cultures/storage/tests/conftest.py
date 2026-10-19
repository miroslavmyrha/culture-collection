"""People, labs, box types and a storage tree for the storage tests, named after what they are.

- lab: Mycology (MYC), fixed public id, one member of every role.
- other_lab: Bacteriology (BAC), managed by `outsider`: the highest role, elsewhere.
- tree: in MYC, freezer "Freezer A" (-80 °C, risk group 2 at most) > rack "Rack 1" in slot 1
  > box "Box 1" (9 x 9) in slot 1, built through the services by the curator.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
from django.contrib.auth.models import update_last_login
from django.contrib.auth.signals import user_logged_in

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import ActorKind, Channel

# The production roles inside the test transaction, the same fixtures the audit tests use.
from cultures.audit.tests.conftest import database_roles, runtime_role  # noqa: F401
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import make_lab, member_of
from cultures.storage import services
from cultures.storage.models import BoxType, StorageUnit, UnitKind
from cultures.users.models import User

LAB_ID = UUID("00000000-0000-4000-8000-00000000000b")
UNITS_URL = f"/api/v1/labs/{LAB_ID}/storage-units/"


@pytest.fixture(autouse=True)
def _no_last_login_update() -> Iterator[None]:
    """Logging in writes users.last_login: keep the history about our writes."""
    user_logged_in.disconnect(dispatch_uid="update_last_login")
    yield
    user_logged_in.connect(update_last_login, dispatch_uid="update_last_login")


@pytest.fixture
def lab() -> Lab:
    return make_lab(public_id=LAB_ID, name="Mycology", code="MYC")


@pytest.fixture
def other_lab() -> Lab:
    return make_lab(name="Bacteriology", code="BAC")


@pytest.fixture
def viewer(lab: Lab) -> User:
    return member_of(lab, Role.VIEWER, "viewer")


@pytest.fixture
def technician(lab: Lab) -> User:
    return member_of(lab, Role.TECHNICIAN, "technician")


@pytest.fixture
def curator(lab: Lab) -> User:
    return member_of(lab, Role.CURATOR, "curator")


@pytest.fixture
def manager(lab: Lab) -> User:
    return member_of(lab, Role.MANAGER, "manager")


@pytest.fixture
def outsider(other_lab: Lab) -> User:
    return member_of(other_lab, Role.MANAGER, "outsider")


@pytest.fixture
def team(viewer: User, technician: User, curator: User, manager: User) -> dict[Role, User]:
    return {
        Role.VIEWER: viewer,
        Role.TECHNICIAN: technician,
        Role.CURATOR: curator,
        Role.MANAGER: manager,
    }


@pytest.fixture
def curator_access(curator: User) -> Access:
    return access_for(curator)


@pytest.fixture
def as_curator(curator: User) -> Iterator[AuditContext]:
    """Services run outside a request: the curator acting through the API channel."""
    with audit_context(channel=Channel.API, actor=curator, request_id="req-1") as context:
        yield context


def make_box_type(name: str = "Cryobox 9 x 9", rows: int = 9, cols: int = 9) -> BoxType:
    with audit_context(
        channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label="command:test"
    ):
        return services.box_type_create(name=name, rows=rows, cols=cols)


@pytest.fixture
def box_9x9() -> BoxType:
    return make_box_type()


@pytest.fixture
def box_10x10() -> BoxType:
    return make_box_type("Cryobox 10 x 10", 10, 10)


MakeUnit = Callable[..., StorageUnit]


@pytest.fixture
def make_unit(lab: Lab, curator: User, box_9x9: BoxType) -> MakeUnit:
    """A unit added by the curator through the service, in its own audit context. A box gets
    the 9 x 9 type unless another is given; a freezer or tank a cap of 2 unless given."""

    def make(
        kind: UnitKind, name: str, parent: StorageUnit | None = None, **fields: Any
    ) -> StorageUnit:
        lab_ = fields.pop("lab", lab)
        actor = fields.pop("actor", curator)
        if kind == UnitKind.BOX:
            fields.setdefault("box_type", box_9x9)
        if parent is None:
            fields.setdefault("max_risk_group", 2)
        with audit_context(channel=Channel.API, actor=actor, request_id="req-setup"):
            return services.unit_create(
                access=access_for(actor),
                lab=lab_,
                data=services.NewUnit(kind=kind, name=name, parent=parent, **fields),
            )

    return make


@dataclass(frozen=True)
class Tree:
    freezer: StorageUnit
    rack: StorageUnit
    box: StorageUnit


@pytest.fixture
def tree(make_unit: MakeUnit) -> Tree:
    freezer = make_unit(UnitKind.FREEZER, "Freezer A", temperature_c=-80)
    rack = make_unit(UnitKind.RACK, "Rack 1", freezer, slot=1)
    box = make_unit(UnitKind.BOX, "Box 1", rack, slot=1)
    return Tree(freezer, rack, box)


def fresh(unit: StorageUnit) -> StorageUnit:
    return StorageUnit.objects.get(pk=unit.pk)

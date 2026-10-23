"""My labs on Home (#69): one entry per lab with the role, the figures the role may see and the
actions it may start."""

from typing import Any

import pytest

from cultures.deposits.tests.support import MakeDeposit
from cultures.distribution.models import Requester
from cultures.distribution.tests.support import Supply, accept_mtas, approve, as_actor, submit
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.lineage import services as lineage
from cultures.lineage.models import Batch
from cultures.lineage.tests.support import vials_of
from cultures.storage import services as storage
from cultures.storage.models import UnitKind, UnitStatus
from cultures.storage.tests.conftest import MakeUnit, Tree
from cultures.users.models import User

from .support import overview

pytestmark = pytest.mark.django_db


def my_lab(user: User) -> dict[str, Any]:
    entries: list[dict[str, Any]] = overview(user)["labs"]
    [entry] = entries
    return entry


@pytest.fixture
def stocked(
    *,
    supply: Supply,
    make_deposit: MakeDeposit,
    lab: Lab,
    requester: Requester,
    curator: User,
    tree: Tree,
    make_unit: MakeUnit,
) -> None:
    """Two strains: one with a released batch of 5 vials (one placed in Box 1), one with a
    batch of 3 pending its checks. Two open requests, one approved (it reserves a vial), one
    received deposit. A second box sits in a freezer out of service."""
    released = supply(vials=5)
    supply(release=False, vials=3)
    placed = vials_of(Batch.objects.get(strain=released))[-1]
    with as_actor(curator):
        lineage.vial_place(access=access_for(curator), vial=placed, box=tree.box, row=1, col=1)
    submit(curator, lab, requester, [(released, 1)])
    approved = submit(curator, lab, requester, [(released, 1)])
    accept_mtas(curator, approved)
    approve(curator, approved)
    make_deposit()
    broken = make_unit(UnitKind.FREEZER, "Freezer B", temperature_c=-80)
    rack = make_unit(UnitKind.RACK, "Rack 1", broken, slot=1)
    make_unit(UnitKind.BOX, "Box 9", rack, slot=1)
    with as_actor(curator):
        storage.unit_set_status(
            access=access_for(curator),
            unit=broken,
            status=UnitStatus.OUT_OF_SERVICE,
            reason="Alarm.",
        )


@pytest.mark.usefixtures("stocked")
@pytest.mark.parametrize(
    ("role", "decide", "check", "actions"),
    [
        (Role.VIEWER, None, None, []),
        (Role.TECHNICIAN, None, None, ["record_check", "find_vial"]),
        (Role.CURATOR, 1, 1, ["receive_deposit", "record_check", "find_vial", "enter_request"]),
        (Role.MANAGER, 1, 1, ["receive_deposit", "record_check", "find_vial", "enter_request"]),
    ],
)
def test_each_role_sees_the_lab_figures_and_its_own_actions(
    role: Role, decide: int | None, check: int | None, actions: list[str], team: dict[Role, User]
) -> None:
    entry = my_lab(team[role])
    assert (entry["code"], entry["name"], entry["role"]) == ("MYC", "Mycology", role)
    assert entry["strains"] == 2
    assert entry["batches"] == {"pending_check": 1, "released": 1, "on_hold": 0, "exhausted": 0}
    # 5 released less the 1 reserved, and the 3 pending: available is a vial's status.
    assert entry["vials_available"] == 4 + 3
    # Box 1 (81 places, one taken); Box 9 is in a freezer out of service.
    assert entry["free_positions"] == 80
    assert entry["open_requests"] == 2
    assert (entry["requests_to_decide"], entry["deposits_to_check"]) == (decide, check)
    assert entry["actions"] == actions


def test_labs_come_by_name_with_the_role_in_each(lab: Lab, other_lab: Lab, curator: User) -> None:
    Membership.objects.create(user=curator, lab=other_lab, role=Role.VIEWER)
    labs = overview(curator)["labs"]
    assert [(e["name"], e["role"]) for e in labs] == [
        ("Bacteriology", "viewer"),
        ("Mycology", "curator"),
    ]
    # Another lab's figures count its own rows only, and a viewer starts nothing there.
    assert (labs[0]["strains"], labs[0]["actions"]) == (0, [])


def test_an_empty_lab_shows_zeros(curator: User) -> None:
    entry = my_lab(curator)
    assert entry["strains"] == entry["vials_available"] == entry["free_positions"] == 0
    assert entry["open_requests"] == entry["requests_to_decide"] == entry["deposits_to_check"] == 0

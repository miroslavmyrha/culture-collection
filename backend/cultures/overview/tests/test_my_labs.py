"""My labs on Home (#69): one entry per lab with the role, the figures the role may see and the
actions it may start."""

from collections.abc import Callable
from typing import Any

import pytest

from cultures.deposits.tests.support import MakeDeposit
from cultures.distribution.models import DistributionRequest, Requester
from cultures.distribution.tests.support import Supply, accept_mtas, approve, as_actor, submit
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.lineage import services as lineage
from cultures.lineage.models import Batch, VialStatus
from cultures.lineage.tests.support import vials_of
from cultures.storage import services as storage
from cultures.storage.models import StorageUnit, UnitKind, UnitStatus
from cultures.storage.selectors import unit_counts
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


STOCKED_VIALS = dict.fromkeys(VialStatus.values, 0) | {"available": 7, "reserved": 1}


@pytest.mark.usefixtures("stocked")
@pytest.mark.parametrize(
    ("role", "to_handle", "actions", "vials"),
    [
        (Role.VIEWER, (None, None), [], None),
        (Role.TECHNICIAN, (None, None), ["record_check", "find_vial"], None),
        (
            Role.CURATOR,
            (1, 1),
            ["receive_deposit", "record_check", "find_vial", "enter_request"],
            None,
        ),
        (
            Role.MANAGER,
            (1, 1),
            ["receive_deposit", "record_check", "find_vial", "enter_request"],
            STOCKED_VIALS,
        ),
    ],
)
def test_each_role_sees_the_lab_figures_and_its_own_actions(
    role: Role,
    to_handle: tuple[int | None, int | None],
    actions: list[str],
    vials: dict[str, int] | None,
    team: dict[Role, User],
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
    assert (entry["requests_to_decide"], entry["deposits_to_check"]) == to_handle
    assert entry["actions"] == actions
    # The states of the vials are the managers' figure (#81); the other roles get null.
    assert entry["vials"] == vials


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


def test_a_manager_sees_the_vials_of_every_state_and_regulated_ones_count_like_the_rest(
    supply: Supply,
    regulated: Callable[..., DistributionRequest],
    curator: User,
    manager: User,
) -> None:
    """A count is no location (ADR 0009 masks the place, not the number): the two reserved vials
    of a dual-use strain count as reserved, the same as an ordinary strain's would."""
    strain = supply(vials=6)
    batch = Batch.objects.get(strain=strain)
    first, second, third, fourth = vials_of(batch)[:4]
    for vial, status in (
        (first, VialStatus.QUARANTINED),
        (second, VialStatus.TO_DESTROY),
        (third, VialStatus.LOST),
        (fourth, VialStatus.CONSUMED),
    ):
        with as_actor(curator):
            lineage.vial_transition(
                access=access_for(curator), vial=vial, status=status, reason="Counted."
            )
    regulated(2)
    entry = my_lab(manager)
    assert entry["vials"] == dict.fromkeys(VialStatus.values, 0) | {
        "available": 2 + 4,  # two of the plain strain, four of the dual-use one
        "reserved": 2,
        "quarantined": 1,
        "to_destroy": 1,
        "lost": 1,
        "consumed": 1,
    }
    assert entry["batches"] == {"pending_check": 0, "released": 2, "on_hold": 0, "exhausted": 0}


def test_a_manager_of_another_lab_sees_its_own_figures_only(
    supply: Supply, outsider: User, curator: User, other_lab: Lab
) -> None:
    supply(vials=5)
    entry = my_lab(outsider)
    assert entry["name"] == other_lab.name
    assert entry["vials"] == dict.fromkeys(VialStatus.values, 0)
    # A manager in one lab and a viewer in another gets the figure only where they manage.
    Membership.objects.create(user=curator, lab=other_lab, role=Role.MANAGER)
    labs = {e["name"]: e["vials"] for e in overview(curator)["labs"]}
    assert labs == {other_lab.name: dict.fromkeys(VialStatus.values, 0), "Mycology": None}


def test_home_and_the_storage_tree_agree_on_the_free_positions(
    tree: Tree, make_unit: MakeUnit, curator: User, lab: Lab
) -> None:
    """Home's figure is the sum of the units' own over the lab's roots (storage.selectors
    .unit_counts), less the boxes that take nothing now because a unit above them is out of
    service. With every unit active the two are equal."""
    make_unit(UnitKind.BOX, "Box 2", tree.rack, slot=2)
    spare = make_unit(UnitKind.FREEZER, "Freezer C", temperature_c=-80)
    spare_rack = make_unit(UnitKind.RACK, "Rack 3", spare, slot=1)
    make_unit(UnitKind.BOX, "Box 3", spare_rack, slot=1)
    retired = make_unit(UnitKind.BOX, "Box 4", tree.rack, slot=3)
    access = access_for(curator)
    with as_actor(curator):
        storage.unit_set_status(
            access=access, unit=retired, status=UnitStatus.RETIRED, reason="Cracked."
        )
    roots = StorageUnit.objects.filter(lab=lab, parent__isnull=True)
    tree_sum = sum(c.free_positions for c in unit_counts(roots).values())
    assert tree_sum == 3 * 81  # the retired box counts nowhere
    assert my_lab(curator)["free_positions"] == tree_sum
    # Out of service: the tree still counts its boxes, Home no longer offers them.
    with as_actor(curator):
        storage.unit_set_status(
            access=access, unit=spare, status=UnitStatus.OUT_OF_SERVICE, reason="Alarm."
        )
    assert sum(c.free_positions for c in unit_counts(roots).values()) == tree_sum
    assert my_lab(curator)["free_positions"] == tree_sum - 81

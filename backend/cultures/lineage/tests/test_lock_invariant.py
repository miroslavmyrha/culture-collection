"""Every public write of cultures.lineage takes the lab lock first.

Each one has a scenario here, run with the SQL captured, or a reviewed exemption. The
captured SQL must show the lab row locked (SELECT ... FROM "labs_lab" ... FOR UPDATE) before
the service reads the actor's role (labs_membership), the strain, a vial, a box or a
placement, reads the location grant, and writes to a lineage table. A placement must lock the
box after the vial (lock order: lab, strain, vial, box). A new service fails until someone
puts it on one side. SQL is text: test_concurrency.py proves what PostgreSQL does.
"""

from collections.abc import Callable

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cultures.audit.context import AuditContext
from cultures.biosafety.models import RestrictionKind
from cultures.biosafety.policy import permit_today
from cultures.labs.access import Access, access_for
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.labs.tests.test_lock_invariant import first, locks, public_services
from cultures.lineage import services
from cultures.lineage.models import CheckKind, Passage, Vial, VialStatus
from cultures.storage.tests.conftest import Tree
from cultures.strains import services as strains
from cultures.strains.services import RestrictionInput
from cultures.users.models import User

from .support import MakeBatch, new_batch, new_check, new_destruction, vials_of

pytestmark = pytest.mark.django_db

Scenario = Callable[[Access, Passage, Vial, Tree], Callable[[], object]]

SCENARIOS: dict[str, Scenario] = {
    "batch_preserve": lambda a, p, v, t: (
        lambda: services.batch_preserve(access=a, passage=p, data=new_batch(box=t.box))
    ),
    "passage_subculture": lambda a, p, v, t: (
        lambda: services.passage_subculture(access=a, parent=p)
    ),
    "vial_revive": lambda a, p, v, t: lambda: services.vial_revive(access=a, vial=v),
    "vial_place": lambda a, p, v, t: (
        lambda: services.vial_place(access=a, vial=v, box=t.box, row=9, col=9)
    ),
    "vials_place": lambda a, p, v, t: _place_several(a, p, t),
    "vial_transition": lambda a, p, v, t: (
        lambda: services.vial_transition(access=a, vial=v, status=VialStatus.LOST, reason="r")
    ),
    "vial_set_barcode": lambda a, p, v, t: (
        lambda: services.vial_set_barcode(access=a, vial=v, barcode="T-1")
    ),
    "vial_reveal_location": lambda a, p, v, t: (
        lambda: services.vial_reveal_location(access=a, vial=v)
    ),
    "check_record": lambda a, p, v, t: _record(a, v),
    "check_enter_in_error": lambda a, p, v, t: _enter_in_error(a, v),
    "batch_release": lambda a, p, v, t: _decide(a, v, services.batch_release),
    "batch_hold": lambda a, p, v, t: _decide(a, v, services.batch_hold),
    "vial_loss_report": lambda a, p, v, t: _report_loss(a, v),
    "destruction_record": lambda a, p, v, t: _record_destruction(a, v),
    "destruction_confirm": lambda a, p, v, t: _confirm_destruction(a, v),
    "destruction_enter_in_error": lambda a, p, v, t: _destruction_in_error(a, v),
}


# The batch is read before the call, as the view does: get_object, then the service.


def _place_several(access: Access, passage: Passage, tree: Tree) -> Callable[[], object]:
    """Two new vials in no box (the scenario's vial is in Box 1 already)."""
    batch = services.batch_preserve(access=access, passage=passage, data=new_batch(vial_count=2))
    first, second = vials_of(batch)
    entries = [
        services.NewPlacement(vial=second, row=9, col=8),
        services.NewPlacement(vial=first, row=9, col=9),
    ]
    return lambda: services.vials_place(access=access, box=tree.box, placements=entries)


def _record(access: Access, vial: Vial) -> Callable[[], object]:
    batch = vial.batch
    return lambda: services.check_record(access=access, batch=batch, data=new_check(vial=vial))


def _enter_in_error(access: Access, vial: Vial) -> Callable[[], object]:
    check = services.check_record(access=access, batch=vial.batch, data=new_check())
    return lambda: services.check_enter_in_error(access=access, check=check, reason="mix-up")


def _decide(access: Access, vial: Vial, decide: Callable[..., object]) -> Callable[[], object]:
    """Three passed checks recorded first, then the decision by the lab's curator (the user the
    batch fixture preserved with)."""
    for kind in CheckKind:
        services.check_record(access=access, batch=vial.batch, data=new_check(kind))
    curator = access_for(User.objects.get(username="curator"))
    batch = vial.batch
    return lambda: decide(access=curator, batch=batch, reason="decided")


def _report_loss(access: Access, vial: Vial) -> Callable[[], object]:
    """The strain made a RAT and the vial lost first; the report by a manager of the lab."""
    curator = User.objects.get(username="curator")
    strains.strain_restriction_add(
        access=access_for(curator),
        strain=vial.batch.strain,
        restriction=RestrictionInput(RestrictionKind.CZ_RAT, "Příloha 2, bod 1"),
        reason="listed",
    )
    lost = services.vial_transition(access=access, vial=vial, status=VialStatus.LOST, reason="r")
    manager = access_for(member_of(vial.lab, Role.MANAGER, "loss-manager"))
    return lambda: services.vial_loss_report(
        access=manager,
        vial=lost,
        lost_at=lost.status_changed_at,  # type: ignore[arg-type]  # set by the transition
        reported_on=permit_today(),
        reference="KRPB-1",
        reason="reported",
    )


def _record_destruction(access: Access, vial: Vial) -> Callable[[], object]:
    """The vial in Box 1 marked to destroy first; a strain without restrictions is destroyed at
    once, so its placement closes too."""
    services.vial_transition(access=access, vial=vial, status=VialStatus.TO_DESTROY, reason="r")
    strain = vial.batch.strain
    return lambda: services.destruction_record(
        access=access, strain=strain, data=new_destruction([vial])
    )


def _confirm_destruction(access: Access, vial: Vial) -> Callable[[], object]:
    """The strain made a RAT, the vial recorded by the technician; a manager confirms."""
    curator = User.objects.get(username="curator")
    strains.strain_restriction_add(
        access=access_for(curator),
        strain=vial.batch.strain,
        restriction=RestrictionInput(RestrictionKind.CZ_RAT, "Příloha 2, bod 1"),
        reason="listed",
    )
    services.vial_transition(access=access, vial=vial, status=VialStatus.TO_DESTROY, reason="r")
    record = services.destruction_record(
        access=access, strain=vial.batch.strain, data=new_destruction([vial])
    )
    manager = access_for(member_of(vial.lab, Role.MANAGER, "destruction-manager"))
    return lambda: services.destruction_confirm(access=manager, record=record)


def _destruction_in_error(access: Access, vial: Vial) -> Callable[[], object]:
    services.vial_transition(access=access, vial=vial, status=VialStatus.TO_DESTROY, reason="r")
    record = services.destruction_record(
        access=access, strain=vial.batch.strain, data=new_destruction([vial])
    )
    return lambda: services.destruction_enter_in_error(access=access, record=record, reason="typo")


EXEMPT: dict[str, str] = {
    "required_for": "a read the destruction services call under their lock",
    "is_regulated": "a read the reveal calls under its lock",
    "kinds_text": "names of kinds joined, no query",
    "latest_checks": "a read the check services call under their lock",
    "not_passed": "a rule on rows already read, no query",
    "location_of": "a read the reveal calls after its commit, and the masked lists never",
    "normalised": "text normalisation, no query",
    "position_label": "a label from two numbers, no query",
    "vial_reserve_locked": (
        "distribution's step, called under its lab and vial locks"
        " (distribution/tests/test_lock_invariant.py)"
    ),
    "vial_release_locked": (
        "distribution's step, called under its lab and vial locks"
        " (distribution/tests/test_lock_invariant.py)"
    ),
    "vial_ship_locked": (
        "distribution's step, called under its lab and vial locks"
        " (distribution/tests/test_lock_invariant.py)"
    ),
    "batch_exhaust_if_emptied_locked": (
        "distribution's step, called under its lab and batch locks"
        " (distribution/tests/test_lock_invariant.py)"
    ),
    "strain_vials_leave_locked": (
        "the deaccession's step, called under its lab and strain locks"
        " (strains/tests/test_lock_invariant.py)"
    ),
}
# Services that write nothing to a lineage table (the reveal writes only its event).
NO_LINEAGE_WRITE = {"vial_reveal_location"}
# Services that move a batch, or may: they lock its row before any vial.
CHECK_SERVICES = {"check_record", "check_enter_in_error", "batch_release", "batch_hold"}


def test_every_public_service_has_a_scenario_or_a_reviewed_exemption() -> None:
    found = public_services(services)
    assert len(found) >= len(SCENARIOS)  # the walk found the services
    assert sorted(found - set(SCENARIOS) - set(EXEMPT)) == []
    assert sorted((set(SCENARIOS) | set(EXEMPT)) - found) == []


def reads(table: str) -> Callable[[str], bool]:
    return lambda sql: sql.startswith("SELECT") and f'FROM "{table}"' in sql


def writes(sql: str) -> bool:
    return sql.startswith(("INSERT INTO", "UPDATE")) and '"lineage_' in sql.split("(", 1)[0]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_lab_lock_comes_first(
    *,
    name: str,
    technician: User,
    passage0: Passage,
    make_batch: MakeBatch,
    tree: Tree,
    as_technician: AuditContext,
) -> None:
    vial = vials_of(make_batch(passage0, vial_count=1, box=tree.box))[0]
    # The access object and the vial are loaded before the capture: the request does that.
    call = SCENARIOS[name](access_for(technician), passage0, vial, tree)
    with CaptureQueriesContext(connection) as captured:
        call()
    statements = [q["sql"] for q in captured.captured_queries]
    lock = first(statements, locks("labs_lab"))
    assert lock is not None, f"{name} never locks the lab:\n" + "\n".join(statements)
    for match in (
        reads("labs_membership"),
        reads("labs_locationgrant"),
        reads("strains_strain"),
        reads("lineage_batch"),
        reads("lineage_batchcheck"),
        reads("lineage_vial"),
        reads("lineage_vialplacement"),
        reads("storage_storageunit"),
        writes,
    ):
        found = first(statements, match)
        assert found is None or found > lock, f"{name}: statement {found} before the lab lock"
    assert (first(statements, writes) is None) == (name in NO_LINEAGE_WRITE), name
    batch_lock, vial_lock, box_lock = (
        first(statements, locks("lineage_batch")),
        first(statements, locks("lineage_vial")),
        first(statements, locks("storage_storageunit")),
    )
    if vial_lock is not None and box_lock is not None:
        assert vial_lock < box_lock, f"{name} locks the box before the vial"
    if batch_lock is not None and vial_lock is not None:
        assert batch_lock < vial_lock, f"{name} locks the vial before the batch"
    if name in CHECK_SERVICES:
        assert batch_lock is not None, f"{name} decides on a batch it never locked"
    if name.startswith("destruction_"):
        strain_lock = first(statements, locks("strains_strain"))
        record_lock = first(statements, locks("lineage_destructionrecord"))
        assert strain_lock is not None, f"{name} never locks the strain"
        assert vial_lock is None or strain_lock < vial_lock, f"{name} locks a vial first"
        if name != "destruction_record":
            assert record_lock is not None, f"{name} changes a record it never locked"
            assert strain_lock < record_lock, f"{name} locks the record before the strain"
            assert vial_lock is None or record_lock < vial_lock, f"{name}: vial before record"
    if name in ("vial_place", "vials_place", "vial_transition", "vial_set_barcode", "vial_revive"):
        assert vial_lock is not None, f"{name} changes a vial it never locked"
    if name in ("vial_place", "vials_place", "batch_preserve"):
        assert box_lock is not None, f"{name} fills a box it never locked"

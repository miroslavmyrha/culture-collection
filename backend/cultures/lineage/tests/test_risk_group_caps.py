"""A strain's risk group never rises above the cap of a box that holds its vials (ADR 0009, the
may_store gate, kept after placement). The refusal names no box: a regulated strain's place
stays masked. Lowering always fits."""

import threading
from collections.abc import Callable

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.core.testing import assert_problem, logged_in, run_before
from cultures.labs.access import access_for
from cultures.labs.tests.test_lock_invariant import first, locks
from cultures.lineage import services as lineage
from cultures.lineage.models import Passage, VialPlacement, VialStatus
from cultures.storage.models import StorageUnit, UnitKind
from cultures.storage.tests.conftest import MakeUnit, Tree
from cultures.strains import services as strains
from cultures.strains.models import Strain
from cultures.strains.tests.conftest import STRAINS_URL
from cultures.users.models import User

from .support import MakeBatch, snapshot, vials_of

pytestmark = pytest.mark.django_db


@pytest.fixture
def boxes(tree: Tree, make_unit: MakeUnit) -> tuple[StorageUnit, StorageUnit]:
    """Freezer A takes group 2 at most: Box 1 inherits 2, Box 1-only is capped at 1."""
    return tree.box, make_unit(UnitKind.BOX, "Box Low", tree.rack, slot=2, max_risk_group=1)


def set_group(curator: User, strain: Strain, group: int) -> Strain:
    return strains.strain_set_risk_group(
        access=access_for(curator), strain=strain, risk_group=group, reason="reassessed"
    )


def refused(call: Callable[[], object]) -> strains.RiskGroupAboveBoxCap:
    before = (snapshot(), list(Strain.objects.values_list("risk_group", flat=True)))
    with pytest.raises(strains.RiskGroupAboveBoxCap) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == ("risk_group_above_box_cap", "risk_group")
    assert (
        raised.value.detail == "A box holding this strain's vials does not allow this risk group."
    )
    assert (snapshot(), list(Strain.objects.values_list("risk_group", flat=True))) == before
    return raised.value


def test_raising_within_the_cap_of_every_box_passes(
    *,
    as_curator: AuditContext,
    curator: User,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    boxes: tuple[StorageUnit, StorageUnit],
) -> None:
    make_batch(passage0, vial_count=2, box=boxes[0])
    assert set_group(curator, strain, 2).risk_group == 2


def test_raising_above_the_cap_of_one_of_several_boxes_is_refused(
    *,
    as_curator: AuditContext,
    curator: User,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    boxes: tuple[StorageUnit, StorageUnit],
) -> None:
    make_batch(passage0, vial_count=1, box=boxes[0])
    make_batch(passage0, vial_count=1, box=boxes[1])
    refused(lambda: set_group(curator, strain, 2))


def test_a_closed_placement_and_another_strain_do_not_count(
    *,
    as_curator: AuditContext,
    curator: User,
    technician: User,
    strain: Strain,
    passage0: Passage,
    regulated: Strain,
    make_batch: MakeBatch,
    boxes: tuple[StorageUnit, StorageUnit],
) -> None:
    left = vials_of(make_batch(passage0, vial_count=1, box=boxes[1]))[0]
    with audit_context(channel=Channel.API, actor=technician):
        lineage.vial_transition(
            access=access_for(technician), vial=left, status=VialStatus.CONSUMED, reason="used"
        )
    make_batch(Passage.objects.get(strain=regulated, number=0), vial_count=1, box=boxes[1])
    assert set_group(curator, strain, 2).risk_group == 2


def test_lowering_always_fits(
    *,
    as_curator: AuditContext,
    curator: User,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    boxes: tuple[StorageUnit, StorageUnit],
) -> None:
    set_group(curator, strain, 2)
    make_batch(passage0, vial_count=1, box=boxes[0])
    StorageUnit.objects.filter(pk=boxes[0].pk).update(max_risk_group=1)  # past the service
    assert set_group(curator, strain, 1).risk_group == 1


def test_a_placement_written_just_before_the_box_read_is_seen(
    *,
    as_curator: AuditContext,
    curator: User,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    boxes: tuple[StorageUnit, StorageUnit],
) -> None:
    """An injected competitor past every lock places a vial in the low box right before the
    service reads the boxes: the service sees it and refuses."""
    vial = vials_of(make_batch(passage0, vial_count=1))[0]

    def competitor() -> None:
        VialPlacement.objects.create(
            lab_id=vial.lab_id,
            vial=vial,
            box=boxes[1],
            row=1,
            col=1,
            placed_at=timezone.now(),
            placed_by=curator,
        )

    with (
        run_before(strains, "_check_boxes_hold", competitor),
        pytest.raises(strains.RiskGroupAboveBoxCap),
    ):
        set_group(curator, strain, 2)


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_a_raise_and_a_placement_at_once_never_both_win(
    *,
    curator: User,
    technician: User,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    boxes: tuple[StorageUnit, StorageUnit],
) -> None:
    vial = vials_of(make_batch(passage0, vial_count=1))[0]
    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}

    def raise_group() -> None:
        try:
            with audit_context(channel=Channel.API, actor=curator, request_id="req-a"):
                barrier.wait(timeout=5)
                set_group(curator, strain, 2)
            outcomes["raise"] = "done"
        except strains.RiskGroupAboveBoxCap:
            outcomes["raise"] = "refused"
        finally:
            connection.close()

    def place() -> None:
        try:
            with audit_context(channel=Channel.API, actor=technician, request_id="req-b"):
                barrier.wait(timeout=5)
                lineage.vial_place(
                    access=access_for(technician), vial=vial, box=boxes[1], row=1, col=1
                )
            outcomes["place"] = "done"
        except lineage.InvalidVial:
            outcomes["place"] = "refused"
        finally:
            connection.close()

    threads = [threading.Thread(target=raise_group), threading.Thread(target=place)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes.values()) == ["done", "refused"], outcomes
    group = Strain.objects.get(pk=strain.pk).risk_group
    placed = VialPlacement.objects.filter(vial=vial, box=boxes[1], removed_at__isnull=True)
    assert (group == 2) != placed.exists()


def test_the_api_refusal_names_no_box(
    *,
    curator: User,
    regulated: Strain,
    make_batch: MakeBatch,
    boxes: tuple[StorageUnit, StorageUnit],
    tree: Tree,
) -> None:
    make_batch(Passage.objects.get(strain=regulated, number=0), vial_count=1, box=boxes[1])
    events = AuditEvent.objects.count()
    response = logged_in(curator).post(
        f"{STRAINS_URL}{regulated.public_id}/risk-group/",
        {"risk_group": 2, "reason": "reassessed"},
        content_type="application/json",
    )
    assert_problem(response, 400, "risk_group_above_box_cap", "risk_group")
    text = response.content.decode()
    for unit in (boxes[1], tree.rack, tree.freezer):
        assert unit.name not in text and str(unit.public_id) not in text
    assert AuditEvent.objects.count() == events


def test_a_raise_locks_the_lab_then_the_strain_then_the_boxes(
    *,
    as_curator: AuditContext,
    curator: User,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    boxes: tuple[StorageUnit, StorageUnit],
) -> None:
    make_batch(passage0, vial_count=1, box=boxes[0])
    access = access_for(curator)
    with CaptureQueriesContext(connection) as captured:
        strains.strain_set_risk_group(access=access, strain=strain, risk_group=2, reason="r")
    sql = [q["sql"] for q in captured.captured_queries]
    order = [first(sql, locks(t)) for t in ("labs_lab", "strains_strain", "storage_storageunit")]
    assert None not in order, sql
    assert order == sorted(order), order  # type: ignore[type-var]

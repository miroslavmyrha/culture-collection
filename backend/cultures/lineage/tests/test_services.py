"""Passages, batches, vials and placements change only through the services: numbering under
the strain's lock, fill order, the may_store gate, the box size, the vial's edges, one event
per change that names its strain, and refusals that change nothing and record nothing."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from django.utils import timezone

from cultures.audit.context import AuditContext, MissingAuditContext
from cultures.audit.models import AuditEvent
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import DomainError, Forbidden, RuleViolation
from cultures.core.testing import run_before
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.test_lock_invariant import public_services
from cultures.lineage import services
from cultures.lineage.models import (
    NOT_IN_A_BOX,
    Batch,
    BatchStatus,
    Passage,
    Purpose,
    Vial,
    VialPlacement,
    VialStatus,
)
from cultures.storage import services as storage
from cultures.storage.models import BoxType, StorageUnit, UnitKind, UnitStatus
from cultures.storage.policy import may_store
from cultures.storage.tests.conftest import MakeUnit, Tree
from cultures.strains import services as strains
from cultures.strains.models import Strain, StrainStatus
from cultures.users.models import User

from .support import MakeBatch, new_batch, open_place, preserve, snapshot, vials_of
from .test_checks import CHECK_SCENARIOS
from .test_constraints import PATHS

pytestmark = pytest.mark.django_db
REASON = "thawed for a viability check"


def refused(
    error: type[DomainError], code: str, call: Callable[[], object], attr: str | None = None
) -> DomainError:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == (code, attr)
    assert snapshot() == before
    return raised.value


def events(since: int = 0) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(pk__gt=since).order_by("pk"))


def last_pk() -> int:
    return AuditEvent.objects.order_by("-pk").values_list("pk", flat=True).first() or 0


# Preservation.


def test_a_technician_preserves_a_batch_and_each_vial_is_an_event(
    as_technician: AuditContext, technician: User, passage0: Passage, strain: Strain
) -> None:
    start = last_pk()
    batch = preserve(technician, passage0, cryoprotectant="  10 %   glycerol ")
    assert (batch.number, batch.strain, batch.passage, batch.lab_id) == (
        1,
        strain,
        passage0,
        strain.lab_id,
    )
    assert (batch.status, batch.purpose, batch.vial_count_created, batch.cryoprotectant) == (
        BatchStatus.PENDING_CHECK,
        Purpose.DISTRIBUTION,
        3,
        "10 % glycerol",
    )
    vials = vials_of(batch)
    assert [(v.seq, v.status, v.lab_id, v.status_changed_at) for v in vials] == [
        (seq, VialStatus.AVAILABLE, strain.lab_id, None) for seq in (1, 2, 3)
    ]
    recorded = events(start)
    assert [e.event_type for e in recorded] == ["batch_created"] + ["vial_created"] * 3 + [
        "vials_created"
    ]
    assert {e.strain_id for e in recorded} == {strain.public_id}
    assert {(e.actor, e.lab_id) for e in recorded} == {(technician, strain.lab_id)}
    assert recorded[0].changes == {
        "number": [None, 1],
        "passage": [None, str(passage0.public_id)],
        "method": [None, "cryo_minus80"],
        "cryoprotectant": [None, "10 % glycerol"],
        "preserved_on": [None, "2026-10-01"],
        "vial_count_created": [None, 3],
        "purpose": [None, "distribution"],
        "status": [None, "pending_check"],
    }
    assert recorded[1].changes == {
        "batch": [None, str(batch.public_id)],
        "seq": [None, 1],
        "status": [None, "available"],
    }
    assert recorded[-1].changes == {"count": [None, 3]}
    assert len({e.batch_id for e in recorded[1:]}) == 1
    assert all(open_place(v) is None for v in vials)  # no box: not placed


def test_batch_numbers_go_up_per_strain(
    as_technician: AuditContext,
    technician: User,
    passage0: Passage,
    regulated: Strain,
) -> None:
    other = Passage.objects.get(strain=regulated, number=0)
    assert [preserve(technician, p).number for p in (passage0, passage0, other, passage0)] == [
        1,
        2,
        1,
        3,
    ]


def test_a_batch_into_a_box_fills_its_free_positions_row_by_row(
    as_technician: AuditContext,
    technician: User,
    passage0: Passage,
    tree: Tree,
) -> None:
    first = preserve(technician, passage0, vial_count=10, box=tree.box)
    assert [open_place(v)[1:] for v in vials_of(first)] == [  # type: ignore[index]
        *((1, col) for col in range(1, 10)),
        (2, 1),
    ]
    # A1 frees up: the next batch takes it first, then carries on after B1.
    (a1,) = [v for v in vials_of(first) if open_place(v)[1:] == (1, 1)]  # type: ignore[index]
    services.vial_transition(
        access=access_for(technician), vial=a1, status=VialStatus.CONSUMED, reason=REASON
    )
    start = last_pk()
    second = preserve(technician, passage0, vial_count=3, box=tree.box)
    assert [open_place(v) for v in vials_of(second)] == [
        (tree.box, 1, 1),
        (tree.box, 2, 2),
        (tree.box, 2, 3),
    ]
    placed = [e for e in events(start) if e.event_type in ("vial_placed", "vials_placed")]
    assert [e.event_type for e in placed] == ["vial_placed"] * 3 + ["vials_placed"]
    assert placed[0].changes == {
        "location": [None, {"box": str(tree.box.public_id), "row": 1, "col": 1}]
    }
    assert {e.strain_id for e in placed} == {passage0.strain.public_id}
    placement = VialPlacement.objects.get(vial=vials_of(second)[0], removed_at__isnull=True)
    assert (placement.placed_by, placement.lab_id) == (technician, passage0.lab_id)


def test_a_box_with_too_few_free_positions_refuses_the_whole_batch(
    as_technician: AuditContext,
    technician: User,
    passage0: Passage,
    tree: Tree,
) -> None:
    preserve(technician, passage0, vial_count=80, box=tree.box)
    error = refused(
        services.InvalidVial,
        "box_full",
        lambda: preserve(technician, passage0, vial_count=2, box=tree.box),
        "box",
    )
    assert error.detail == "This box has 1 free positions, the batch 2 vials."


@pytest.mark.parametrize(
    ("unit", "code"),
    [("rack", "not_a_box"), ("freezer", "not_a_box"), ("capped", "risk_group_above_cap")],
)
def test_preserving_into_a_box_asks_may_store(
    *,
    as_technician: AuditContext,
    technician: User,
    tree: Tree,
    make_unit: MakeUnit,
    regulated: Strain,
    curator: User,
    unit: str,
    code: str,
) -> None:
    strains.strain_set_risk_group(
        access=access_for(curator), strain=regulated, risk_group=2, reason="reassessed"
    )
    targets = {
        "rack": tree.rack,
        "freezer": tree.freezer,
        "capped": make_unit(UnitKind.BOX, "Box 1 only", tree.rack, slot=2, max_risk_group=1),
    }
    passage = Passage.objects.get(strain=regulated, number=0)
    refused(
        services.InvalidVial,
        code,
        lambda: preserve(technician, passage, box=targets[unit]),
        "box",
    )


def test_a_box_out_of_service_takes_nothing(
    as_technician: AuditContext, technician: User, curator: User, passage0: Passage, tree: Tree
) -> None:
    storage.unit_set_status(
        access=access_for(curator), unit=tree.freezer, status=UnitStatus.OUT_OF_SERVICE, reason="r"
    )
    refused(
        services.InvalidVial,
        "unit_not_active",
        lambda: preserve(technician, passage0, box=tree.box),
        "box",
    )


def test_a_box_of_another_lab_is_unknown(
    *,
    as_technician: AuditContext,
    technician: User,
    passage0: Passage,
    other_lab: Lab,
    outsider: User,
    make_unit: MakeUnit,
) -> None:
    Membership.objects.filter(user=outsider).update(role=Role.CURATOR)
    freezer = make_unit(UnitKind.FREEZER, "F", lab=other_lab, actor=outsider)
    box = make_unit(UnitKind.BOX, "B", freezer, lab=other_lab, actor=outsider)
    refused(
        services.InvalidVial,
        "does_not_exist",
        lambda: preserve(technician, passage0, box=box),
        "box",
    )


# The changes are built when the test runs: a date taken while the tests are collected goes
# stale when the run crosses midnight (CI on 2026-10-25 collected at 23:55 and ran after 00:00).
@pytest.mark.parametrize(
    ("changes", "attr", "code"),
    [
        (lambda: {"vial_count": 0}, "vial_count", "invalid"),
        (lambda: {"vial_count": 201}, "vial_count", "invalid"),
        (lambda: {"preserved_on": permit_today() + timedelta(days=1)}, "preserved_on", "invalid"),
    ],
)
def test_preservation_checks_its_input(
    *,
    as_technician: AuditContext,
    technician: User,
    passage0: Passage,
    changes: Callable[[], dict[str, Any]],
    attr: str,
    code: str,
) -> None:
    refused(services.InvalidVial, code, lambda: preserve(technician, passage0, **changes()), attr)


def test_preserving_today_is_allowed(
    as_technician: AuditContext, technician: User, passage0: Passage
) -> None:
    assert preserve(technician, passage0, preserved_on=permit_today()).preserved_on == (
        permit_today()
    )


def test_a_deaccessioned_strain_is_not_preserved(
    as_technician: AuditContext, technician: User, passage0: Passage
) -> None:
    Strain.objects.filter(pk=passage0.strain_id).update(status=StrainStatus.DEACCESSIONED)
    refused(services.StrainNotActive, "strain_not_active", lambda: preserve(technician, passage0))


# Passages.


def test_a_subculture_is_one_passage_more_and_an_event(
    as_technician: AuditContext, technician: User, passage0: Passage, strain: Strain
) -> None:
    access = access_for(technician)
    first = services.passage_subculture(access=access, parent=passage0)
    second = services.passage_subculture(access=access, parent=first)
    assert [(p.number, p.source_passage) for p in (first, second)] == [(1, passage0), (2, first)]
    event = events()[-1]
    assert (event.event_type, event.strain_id, event.subject_id) == (
        "passage_created",
        strain.public_id,
        second.public_id,
    )
    assert event.changes == {"number": [None, 2], "source_passage": [None, str(first.public_id)]}


def test_a_revival_consumes_the_vial_and_starts_a_passage(
    as_technician: AuditContext,
    technician: User,
    passage0: Passage,
    strain: Strain,
    tree: Tree,
) -> None:
    access = access_for(technician)
    one = services.passage_subculture(access=access, parent=passage0)
    vial = vials_of(preserve(technician, one, vial_count=1, box=tree.box))[0]
    start = last_pk()
    revived = services.vial_revive(access=access, vial=vial)
    assert (revived.number, revived.source_vial, revived.strain) == (2, vial, strain)
    vial.refresh_from_db()
    assert vial.status == VialStatus.CONSUMED
    assert open_place(vial) is None
    closed = VialPlacement.objects.get(vial=vial)
    assert (closed.removal_reason, closed.removed_by) == ("consumed", technician)
    recorded = events(start)
    assert [e.event_type for e in recorded] == ["vial_status_changed", "passage_created"]
    assert recorded[0].reason == "Revived as passage 2."
    assert recorded[0].changes == {
        "status": ["available", "consumed"],
        "location": [{"box": str(tree.box.public_id), "row": 1, "col": 1}, None],
    }
    assert recorded[1].changes == {"number": [None, 2], "source_vial": [None, str(vial.public_id)]}
    assert {e.strain_id for e in recorded} == {strain.public_id}
    refused(
        services.EdgeNotAllowed,
        "transition_not_allowed",
        lambda: services.vial_revive(access=access, vial=vial),
        "status",
    )


# Placement.


@pytest.fixture
def vial(make_batch: MakeBatch, passage0: Passage) -> Vial:
    return vials_of(make_batch(passage0, vial_count=2))[0]


def place(actor: User, vial: Vial, box: StorageUnit, row: int, col: int) -> Vial:
    return services.vial_place(access=access_for(actor), vial=vial, box=box, row=row, col=col)


def test_a_vial_is_placed_and_moved_and_the_old_row_stays(
    as_technician: AuditContext, technician: User, vial: Vial, tree: Tree, make_unit: MakeUnit
) -> None:
    start = last_pk()
    place(technician, vial, tree.box, 2, 3)
    assert open_place(vial) == (tree.box, 2, 3)
    other = make_unit(UnitKind.BOX, "Box 2", tree.rack, slot=2)
    place(technician, vial, other, 9, 9)
    assert open_place(vial) == (other, 9, 9)
    rows = list(VialPlacement.objects.filter(vial=vial).order_by("pk"))
    assert [(r.box, r.row, r.col, r.removal_reason) for r in rows] == [
        (tree.box, 2, 3, "moved"),
        (other, 9, 9, ""),
    ]
    assert rows[0].removed_at == rows[1].placed_at
    recorded = [e for e in events(start) if e.subject_type == "vial"]
    assert [e.event_type for e in recorded] == ["vial_placed", "vial_moved"]
    assert recorded[1].changes == {
        "location": [
            {"box": str(tree.box.public_id), "row": 2, "col": 3},
            {"box": str(other.public_id), "row": 9, "col": 9},
        ]
    }
    assert {e.strain_id for e in recorded} == {vial.batch.strain.public_id}
    # The same position again changes nothing and records nothing.
    before = snapshot()
    place(technician, vial, other, 9, 9)
    assert snapshot() == before


@pytest.mark.parametrize(
    ("row", "col", "attr", "detail"),
    [
        (10, 1, "row", "This box has 9 rows."),
        (1, 10, "col", "This box has 9 columns."),
        (0, 1, "row", "Rows are counted from 1."),
        (1, 0, "col", "Columns are counted from 1."),
    ],
)
def test_a_position_lies_inside_the_box(
    *,
    as_technician: AuditContext,
    technician: User,
    vial: Vial,
    tree: Tree,
    row: int,
    col: int,
    attr: str,
    detail: str,
) -> None:
    error = refused(
        services.InvalidVial,
        "outside_box",
        lambda: place(technician, vial, tree.box, row, col),
        attr,
    )
    assert error.detail == detail


def test_a_taken_position_is_refused(
    as_technician: AuditContext,
    technician: User,
    make_batch: MakeBatch,
    passage0: Passage,
    tree: Tree,
) -> None:
    first, second = vials_of(make_batch(passage0, vial_count=2))
    place(technician, first, tree.box, 4, 4)
    refused(
        services.PositionTaken, "position_taken", lambda: place(technician, second, tree.box, 4, 4)
    )


@pytest.mark.parametrize("status", sorted(NOT_IN_A_BOX))
@pytest.mark.usefixtures("vial_edges_alone")  # distributed without a shipment of #88
def test_a_vial_out_of_the_collection_has_no_place(
    as_technician: AuditContext, technician: User, vial: Vial, tree: Tree, status: VialStatus
) -> None:
    for step in PATHS[status]:  # along the edges, past the service
        Vial.objects.filter(pk=vial.pk).update(status=step, status_changed_at=timezone.now())
    refused(
        services.VialNotInCollection,
        "vial_not_in_collection",
        lambda: place(technician, vial, tree.box, 1, 1),
    )


def test_placing_asks_may_store_under_the_lab_lock(
    *,
    as_technician: AuditContext,
    technician: User,
    vial: Vial,
    tree: Tree,
    curator: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[int, int]] = []
    real = may_store

    def spy(*, unit: StorageUnit, risk_group: int) -> Any:
        asked.append((unit.pk, risk_group))
        return real(unit=unit, risk_group=risk_group)

    monkeypatch.setattr("cultures.lineage.services._shared.may_store", spy)
    place(technician, vial, tree.box, 1, 1)
    assert asked == [(tree.box.pk, 1)]
    storage.unit_update(
        access=access_for(curator),
        unit=tree.freezer,
        fields=storage.UnitFields(name="Freezer A", temperature_c=-80, max_risk_group=1),
    )
    strain = vial.batch.strain
    # Raised past the cap of the freezer: the next placement of its vials is refused.
    Strain.objects.filter(pk=strain.pk).update(risk_group=2)
    refused(
        services.InvalidVial,
        "risk_group_above_cap",
        lambda: place(technician, vial, tree.box, 1, 2),
        "box",
    )


# States.


def test_a_vial_that_leaves_closes_its_placement_in_the_same_event(
    as_technician: AuditContext, technician: User, vial: Vial, tree: Tree
) -> None:
    access = access_for(technician)
    place(technician, vial, tree.box, 5, 5)
    services.vial_transition(access=access, vial=vial, status=VialStatus.TO_DESTROY, reason=REASON)
    assert open_place(vial) == (tree.box, 5, 5)  # still in the box until destroyed
    start = last_pk()
    services.vial_transition(access=access, vial=vial, status=VialStatus.DESTROYED, reason=REASON)
    assert open_place(vial) is None
    (event,) = events(start)
    assert (event.event_type, event.reason, event.strain_id) == (
        "vial_status_changed",
        REASON,
        vial.batch.strain.public_id,
    )
    assert event.changes == {
        "status": ["to_destroy", "destroyed"],
        "location": [{"box": str(tree.box.public_id), "row": 5, "col": 5}, None],
    }
    assert VialPlacement.objects.get(vial=vial).removal_reason == "destroyed"
    vial.refresh_from_db()
    assert vial.status_changed_at is not None


def test_a_lost_vial_is_found_and_placed_again(
    as_technician: AuditContext, technician: User, vial: Vial, tree: Tree
) -> None:
    access = access_for(technician)
    place(technician, vial, tree.box, 1, 1)
    services.vial_transition(access=access, vial=vial, status=VialStatus.LOST, reason="not there")
    assert VialPlacement.objects.get(vial=vial).removal_reason == "lost"
    services.vial_transition(access=access, vial=vial, status=VialStatus.AVAILABLE, reason="found")
    place(technician, vial, tree.box, 1, 1)
    assert open_place(vial) == (tree.box, 1, 1)


@pytest.mark.parametrize("status", [VialStatus.RESERVED, VialStatus.DISTRIBUTED])
def test_reservation_and_dispatch_are_not_set_by_hand(
    as_technician: AuditContext, technician: User, vial: Vial, status: VialStatus
) -> None:
    refused(
        services.EdgeNotAllowed,
        "transition_not_allowed",
        lambda: services.vial_transition(
            access=access_for(technician), vial=vial, status=status, reason=REASON
        ),
        "status",
    )


def test_a_state_change_needs_a_reason(
    as_technician: AuditContext, technician: User, vial: Vial
) -> None:
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.vial_transition(
            access=access_for(technician), vial=vial, status=VialStatus.LOST, reason="  "
        ),
        "reason",
    )


# Barcodes.


def test_a_barcode_is_set_corrected_and_unique_in_the_lab(
    as_technician: AuditContext, technician: User, make_batch: MakeBatch, passage0: Passage
) -> None:
    access = access_for(technician)
    first, second = vials_of(make_batch(passage0, vial_count=2))
    services.vial_set_barcode(access=access, vial=first, barcode=" TUBE-1 ")
    services.vial_set_barcode(access=access, vial=first, barcode="TUBE-2")
    assert Vial.objects.get(pk=first.pk).barcode == "TUBE-2"
    assert [e.changes for e in events() if e.event_type == "vial_barcode_set"] == [
        {"barcode": [None, "TUBE-1"]},
        {"barcode": ["TUBE-1", "TUBE-2"]},
    ]
    refused(
        services.InvalidVial,
        "unique",
        lambda: services.vial_set_barcode(access=access, vial=second, barcode="TUBE-2"),
        "barcode",
    )
    refused(
        services.InvalidVial,
        "invalid",
        lambda: services.vial_set_barcode(access=access, vial=second, barcode="TU BE"),
        "barcode",
    )
    services.vial_set_barcode(access=access, vial=first, barcode="")
    assert Vial.objects.get(pk=first.pk).barcode is None


# Storage now sees the vials: box_occupied, resizing, retiring and caps.


def test_box_occupied_counts_open_placements(
    as_technician: AuditContext, technician: User, vial: Vial, tree: Tree
) -> None:
    assert storage.box_occupied(tree.box) is False
    place(technician, vial, tree.box, 1, 1)
    assert storage.box_occupied(tree.box) is True
    services.vial_transition(
        access=access_for(technician), vial=vial, status=VialStatus.CONSUMED, reason=REASON
    )
    assert storage.box_occupied(tree.box) is False


def test_an_occupied_box_keeps_its_size_and_is_not_retired(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    vial: Vial,
    tree: Tree,
    box_10x10: BoxType,
) -> None:
    place(technician, vial, tree.box, 1, 1)
    access = access_for(curator)
    refused(
        storage.BoxOccupied,
        "box_occupied",
        lambda: storage.unit_update(
            access=access,
            unit=tree.box,
            fields=storage.UnitFields(name="Box 1", box_type=box_10x10),
        ),
        "box_type",
    )
    refused(
        storage.UnitNotEmpty,
        "unit_not_empty",
        lambda: storage.unit_set_status(
            access=access, unit=tree.box, status=UnitStatus.RETIRED, reason="cracked"
        ),
    )


def test_a_cap_does_not_go_below_what_a_unit_holds(
    as_technician: AuditContext, technician: User, curator: User, vial: Vial, tree: Tree
) -> None:
    access = access_for(curator)
    Strain.objects.filter(pk=vial.batch.strain_id).update(risk_group=2)
    place(technician, vial, tree.box, 1, 1)

    def lower(unit: StorageUnit, name: str) -> object:
        fields = storage.UnitFields(
            name=name, max_risk_group=1, temperature_c=unit.temperature_c, box_type=unit.box_type
        )
        return storage.unit_update(access=access, unit=unit, fields=fields)

    for unit, name in ((tree.freezer, "Freezer A"), (tree.rack, "Rack 1"), (tree.box, "Box 1")):
        refused(
            storage.InvalidUnit,
            "cap_below_held",
            lambda unit=unit, name=name: lower(unit, name),  # type: ignore[misc]
            "max_risk_group",
        )


def test_a_unit_is_not_moved_under_a_lower_cap_than_it_holds(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    vial: Vial,
    tree: Tree,
    make_unit: MakeUnit,
) -> None:
    Strain.objects.filter(pk=vial.batch.strain_id).update(risk_group=2)
    place(technician, vial, tree.box, 1, 1)
    low = make_unit(UnitKind.FREEZER, "Freezer RG1", max_risk_group=1)
    refused(
        storage.InvalidUnit,
        "cap_below_held",
        lambda: storage.unit_move(
            access=access_for(curator), unit=tree.rack, parent=low, slot=None
        ),
        "parent",
    )
    high = make_unit(UnitKind.FREEZER, "Freezer RG2", max_risk_group=2)
    storage.unit_move(access=access_for(curator), unit=tree.rack, parent=high, slot=None)


# Who may, and the audit context.


SCENARIOS: dict[str, Callable[[Access, Passage, Vial, Tree], object]] = {
    "batch_preserve": lambda a, p, v, t: services.batch_preserve(
        access=a, passage=p, data=new_batch(box=t.box)
    ),
    "passage_subculture": lambda a, p, v, t: services.passage_subculture(access=a, parent=p),
    "vial_revive": lambda a, p, v, t: services.vial_revive(access=a, vial=v),
    "vial_place": lambda a, p, v, t: services.vial_place(access=a, vial=v, box=t.box, row=9, col=9),
    "vial_transition": lambda a, p, v, t: services.vial_transition(
        access=a, vial=v, status=VialStatus.QUARANTINED, reason=REASON
    ),
    "vial_set_barcode": lambda a, p, v, t: services.vial_set_barcode(
        access=a, vial=v, barcode="T-9"
    ),
    "vial_reveal_location": lambda a, p, v, t: services.vial_reveal_location(access=a, vial=v),
}
# Reads and helpers: no lab to lock, nothing written.
NOT_A_WRITE = {
    "is_regulated",
    "kinds_text",
    "latest_checks",
    "location_of",
    "normalised",
    "not_passed",
    "position_label",
}
# Distribution's steps: written under its locks, walked by distribution/tests/test_services.py.
DISTRIBUTION_STEPS = {
    "vial_reserve_locked",
    "vial_release_locked",
    "vial_ship_locked",
    "batch_exhaust_if_emptied_locked",
}
# Viewers may reveal (strains.view): the grant decides, tested in test_masking.py.
VIEWER_MAY = {"vial_reveal_location"}


def test_every_service_has_a_scenario_here() -> None:
    """The check services have theirs in test_checks.py (their setup needs a batch)."""
    found = public_services(services)
    assert {"batch_preserve", "vial_place", "check_record"} <= found  # the walk found them
    assert found - NOT_A_WRITE - DISTRIBUTION_STEPS == set(SCENARIOS) | set(CHECK_SCENARIOS)
    assert not set(SCENARIOS) & set(CHECK_SCENARIOS)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_event_names_the_strain(
    *,
    name: str,
    as_technician: AuditContext,
    technician: User,
    passage0: Passage,
    regulated: Strain,
    vial: Vial,
    tree: Tree,
    keeper: User,
) -> None:
    # The keeper reveals a regulated vial, so the reveal records an event too.
    actor = keeper if name == "vial_reveal_location" else technician
    target = vial
    if name == "vial_reveal_location":
        regulated_passage = Passage.objects.get(strain=regulated, number=0)
        batch = preserve(technician, regulated_passage, vial_count=1, box=tree.box)
        target = vials_of(batch)[0]
    start = last_pk()
    SCENARIOS[name](access_for(actor), passage0, target, tree)
    recorded = events(start)
    assert recorded, name
    assert {e.strain_id for e in recorded} == {target.batch.strain.public_id}, name
    assert {e.lab_id for e in recorded} == {passage0.lab_id}, name


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_a_technician_demoted_since_the_request_began_is_refused(
    *,
    name: str,
    as_technician: AuditContext,
    technician: User,
    lab: Lab,
    passage0: Passage,
    vial: Vial,
    tree: Tree,
) -> None:
    access = access_for(technician)  # built while the technician was one
    role = Role.VIEWER if name not in VIEWER_MAY else None
    if role is None:
        Membership.objects.filter(user=technician, lab=lab).delete()
    else:
        Membership.objects.filter(user=technician, lab=lab).update(role=role)
    refused(Forbidden, "permission_denied", lambda: SCENARIOS[name](access, passage0, vial, tree))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_service_needs_an_audit_context(
    name: str, technician: User, passage0: Passage, vial: Vial, tree: Tree
) -> None:
    before = snapshot()
    with pytest.raises(MissingAuditContext):
        SCENARIOS[name](access_for(technician), passage0, vial, tree)
    assert snapshot() == before


def test_a_batch_number_taken_at_the_same_moment_is_a_conflict(
    as_technician: AuditContext,
    technician: User,
    passage0: Passage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unique (strain, number) is the final arbiter: a writer that skipped the strain's
    lock and took the number between the read and the insert loses nothing but a retry."""

    def competitor() -> None:
        Batch.objects.create(
            lab_id=passage0.lab_id,
            strain_id=passage0.strain_id,
            passage=passage0,
            number=1,
            method="cryo_ln2",
            preserved_on=date(2026, 1, 1),
            vial_count_created=1,
            purpose="seed",
        )

    with (
        run_before(services.passages, "_save", competitor),
        pytest.raises(services.BatchNumberTaken),
    ):
        preserve(technician, passage0)

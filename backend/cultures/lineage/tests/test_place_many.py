"""Several vials into one box in one step (#77): the service and the box's place action.

- Every rule of a single placement holds for each vial, and one refusal changes nothing: no
  vial is placed, no event recorded.
- A refusal names the entry by its index (`placements.<i>.vial`, `.row`, `.col`, or
  `placements.<i>` for the position), never a box or a place the caller did not send.
- One vial_placed per vial and one vials_placed, sharing the batch.
- Technicians and up place; viewers get 403 before the input is read, outsiders 404.
- No answer and no refusal carries where a regulated strain's vial is (ADR 0009).
- The action's query count is exact and does not grow with the number of vials.
"""

from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.core.testing import QueryBaseline, assert_problem, logged_in, run_before
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.lineage import services
from cultures.lineage.models import Passage, Vial, VialPlacement, VialStatus
from cultures.lineage.tests.test_box_grid import identities
from cultures.lineage.tests.test_masking import leaks
from cultures.storage import services as storage
from cultures.storage.models import StorageUnit, UnitKind
from cultures.storage.tests.conftest import MakeUnit, Tree, make_box_type
from cultures.strains.models import Strain
from cultures.users.models import User

from .support import LAB_URL, MakeBatch, new_batch, open_place, snapshot, vials_of

pytestmark = pytest.mark.django_db
BOXES_URL = f"{LAB_URL}/boxes/"
ROLES = [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR, Role.MANAGER]


@pytest.fixture
def loose(make_batch: MakeBatch, passage0: Passage) -> list[Vial]:
    """Three vials of the plain strain in no box."""
    return vials_of(make_batch(passage0, vial_count=3))


def entries(*rows: tuple[Vial, int, int]) -> list[services.NewPlacement]:
    return [services.NewPlacement(vial=v, row=r, col=c) for v, r, c in rows]


def place(actor: User, box: StorageUnit, *rows: tuple[Vial, int, int]) -> list[Vial]:
    return services.vials_place(access=access_for(actor), box=box, placements=entries(*rows))


def refused(error: type[Exception], code: str, attr: str | None, call: Any) -> Any:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == (code, attr)  # type: ignore[attr-defined]
    assert snapshot() == before
    return raised.value


def body(*rows: tuple[Vial, int, int]) -> dict[str, Any]:
    return {"placements": [{"vial": str(v.public_id), "row": r, "col": c} for v, r, c in rows]}


def post(user: User | None, box: StorageUnit, payload: dict[str, Any]) -> Any:
    return logged_in(user).post(
        f"{BOXES_URL}{box.public_id}/place/", payload, content_type="application/json"
    )


# The service.


def test_several_vials_go_into_one_box_with_one_batch_of_events(
    as_technician: AuditContext, technician: User, loose: list[Vial], tree: Tree
) -> None:
    start = AuditEvent.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
    a, b, c = loose
    placed = place(technician, tree.box, (c, 1, 1), (a, 1, 3), (b, 2, 2))
    assert placed == [c, a, b]  # in the order asked
    assert [open_place(v) for v in (c, a, b)] == [
        (tree.box, 1, 1),
        (tree.box, 1, 3),
        (tree.box, 2, 2),
    ]
    recorded = list(AuditEvent.objects.filter(pk__gt=start).order_by("pk"))
    assert [e.event_type for e in recorded] == ["vial_placed"] * 3 + ["vials_placed"]
    assert len({e.batch_id for e in recorded}) == 1
    assert [e.subject_id for e in recorded[:3]] == [c.public_id, a.public_id, b.public_id]
    box = str(tree.box.public_id)
    assert [e.changes for e in recorded[:3]] == [
        {"location": [None, {"box": box, "row": 1, "col": 1}]},
        {"location": [None, {"box": box, "row": 1, "col": 3}]},
        {"location": [None, {"box": box, "row": 2, "col": 2}]},
    ]
    assert recorded[3].changes == {"count": [None, 3]}
    assert {e.strain_id for e in recorded} == {a.batch.strain.public_id}


@pytest.mark.parametrize(
    ("last", "error", "code", "attr"),
    [
        ((10, 1), services.InvalidVial, "outside_box", "placements.2.row"),
        ((1, 10), services.InvalidVial, "outside_box", "placements.2.col"),
        ((5, 5), services.PositionTaken, "position_taken", "placements.2"),
    ],
    ids=["row outside", "column outside", "taken"],
)
def test_one_bad_position_refuses_every_vial(
    *,
    as_technician: AuditContext,
    technician: User,
    loose: list[Vial],
    make_batch: MakeBatch,
    passage0: Passage,
    tree: Tree,
    last: tuple[int, int],
    error: type[Exception],
    code: str,
    attr: str,
) -> None:
    make_batch(passage0, vial_count=1, box=tree.box)  # A1
    occupant = vials_of(make_batch(passage0, vial_count=1))[0]
    place(technician, tree.box, (occupant, 5, 5))
    a, b, c = loose
    refused(
        error, code, attr, lambda: place(technician, tree.box, (a, 2, 1), (b, 2, 2), (c, *last))
    )
    assert [open_place(v) for v in loose] == [None, None, None]


def test_two_vials_to_one_position_are_refused(
    as_technician: AuditContext, technician: User, loose: list[Vial], tree: Tree
) -> None:
    a, b, c = loose
    refused(
        services.InvalidVial,
        "position_twice",
        "placements.2",
        lambda: place(technician, tree.box, (a, 3, 3), (b, 3, 4), (c, 3, 3)),
    )


def test_a_vial_twice_in_the_list_is_refused(
    as_technician: AuditContext, technician: User, loose: list[Vial], tree: Tree
) -> None:
    a, b, _ = loose
    refused(
        services.InvalidVial,
        "duplicate",
        "placements.2.vial",
        lambda: place(technician, tree.box, (a, 3, 3), (b, 3, 4), (a, 3, 5)),
    )


def test_a_vial_in_a_box_already_is_not_moved_here(
    as_technician: AuditContext,
    technician: User,
    loose: list[Vial],
    tree: Tree,
    make_unit: MakeUnit,
) -> None:
    other = make_unit(UnitKind.BOX, "Box 2", tree.rack, slot=2)
    a, b, _ = loose
    place(technician, other, (b, 1, 1))
    refused(
        services.VialAlreadyPlaced,
        "vial_already_placed",
        "placements.1.vial",
        lambda: place(technician, tree.box, (a, 1, 1), (b, 1, 2)),
    )
    assert open_place(b) == (other, 1, 1)


@pytest.mark.parametrize("status", [VialStatus.LOST, VialStatus.CONSUMED])
def test_a_vial_out_of_the_collection_is_refused(
    *,
    as_technician: AuditContext,
    technician: User,
    loose: list[Vial],
    tree: Tree,
    status: VialStatus,
) -> None:
    a, b, _ = loose
    Vial.objects.filter(pk=b.pk).update(status=status, status_changed_at=timezone.now())
    refused(
        services.VialNotInCollection,
        "vial_not_in_collection",
        "placements.1.vial",
        lambda: place(technician, tree.box, (a, 1, 1), (b, 1, 2)),
    )


def test_a_position_taken_at_the_same_moment_refuses_every_vial(
    as_technician: AuditContext, technician: User, loose: list[Vial], tree: Tree, passage0: Passage
) -> None:
    """The unique open position is the final arbiter: a writer that skipped the locks and took
    a position between the check and the insert leaves nothing of this call placed."""
    a, b, c = loose
    intruder = vials_of(
        services.batch_preserve(
            access=access_for(technician), passage=passage0, data=new_batch(vial_count=1)
        )
    )[0]

    def competitor() -> None:
        VialPlacement.objects.create(
            lab_id=tree.box.lab_id,
            vial=intruder,
            box=tree.box,
            row=4,
            col=3,
            placed_at=timezone.now(),
            placed_by=technician,
        )

    with (
        run_before(services.vials, "_save_all", competitor),
        pytest.raises(services.PositionTaken) as raised,
    ):
        place(technician, tree.box, (a, 4, 1), (b, 4, 2), (c, 4, 3))
    assert raised.value.attr is None  # which entry lost is not known here
    assert [open_place(v) for v in loose] == [None, None, None]


def test_a_strain_above_the_box_cap_names_its_vial(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    loose: list[Vial],
    tree: Tree,
) -> None:
    storage.unit_update(
        access=access_for(curator),
        unit=tree.freezer,
        fields=storage.UnitFields(name="Freezer A", temperature_c=-80, max_risk_group=1),
    )
    Strain.objects.filter(pk=loose[0].batch.strain_id).update(risk_group=2)
    a, b, _ = loose
    refused(
        services.InvalidVial,
        "risk_group_above_cap",
        "placements.0.vial",
        lambda: place(technician, tree.box, (a, 1, 1), (b, 1, 2)),
    )


def test_a_vial_of_another_lab_is_unknown_there(
    technician: User, loose: list[Vial], other_lab: Lab
) -> None:
    """The input resolves vials of every lab where the caller handles vials; the service keeps
    the box's lab, with the same message as an unknown id."""
    Membership.objects.create(user=technician, lab=other_lab, role=Role.CURATOR)
    with audit_context(channel=Channel.API, actor=technician):
        access = access_for(technician)
        freezer = storage.unit_create(
            access=access,
            lab=other_lab,
            data=storage.NewUnit(UnitKind.FREEZER, "F", max_risk_group=2),
        )
        box = storage.unit_create(
            access=access,
            lab=other_lab,
            data=storage.NewUnit(UnitKind.BOX, "B", freezer, box_type=make_box_type("Other")),
        )
    before = snapshot()
    response = logged_in(technician).post(
        f"/api/v1/labs/{other_lab.public_id}/boxes/{box.public_id}/place/",
        body((loose[0], 1, 1)),
        content_type="application/json",
    )
    problem = assert_problem(response, 400, "does_not_exist", "placements.0.vial")
    assert problem["errors"][0]["detail"] == "Invalid vial."
    assert snapshot() == before


def test_the_vials_are_locked_in_pk_order_before_the_box(
    as_technician: AuditContext, technician: User, loose: list[Vial], tree: Tree
) -> None:
    """Two calls that share vials take their locks in the same order, whatever order each
    lists them in (django-patterns traps: sorted lock order against deadlocks)."""
    a, b, c = loose
    with CaptureQueriesContext(connection) as captured:
        place(technician, tree.box, (c, 1, 1), (a, 1, 2), (b, 1, 3))
    sql = [q["sql"] for q in captured.captured_queries]
    vial_lock = next(
        i for i, s in enumerate(sql) if 'FROM "lineage_vial"' in s and "FOR UPDATE" in s
    )
    box_lock = next(
        i for i, s in enumerate(sql) if 'FROM "storage_storageunit"' in s and "FOR UPDATE" in s
    )
    assert vial_lock < box_lock
    assert 'ORDER BY "lineage_vial"."id" ASC' in sql[vial_lock]


# The API.


@pytest.mark.parametrize("role", ROLES)
def test_technicians_and_up_place_and_a_viewer_gets_403_before_the_input(
    role: Role, team: dict[Role, User], loose: list[Vial], tree: Tree
) -> None:
    before = snapshot()
    a, b, _ = loose
    if role == Role.VIEWER:
        assert_problem(post(team[role], tree.box, {"placements": "x"}), 403, "permission_denied")
        assert snapshot() == before
        return
    response = post(team[role], tree.box, body((a, 1, 1), (b, 2, 1)))
    assert response.status_code == 200, response.content
    rows = response.json()["vials"]
    assert [r["public_id"] for r in rows] == [str(a.public_id), str(b.public_id)]
    assert [r["location"]["label"] for r in rows] == ["A1", "B1"]
    assert rows[0]["location"]["path"] == ["Freezer A", "Rack 1", "Box 1"]


def test_anonymous_gets_401_and_an_outsider_404(
    loose: list[Vial], tree: Tree, outsider: User
) -> None:
    before = snapshot()
    assert_problem(post(None, tree.box, body((loose[0], 1, 1))), 401, "not_authenticated")
    assert_problem(post(outsider, tree.box, body((loose[0], 1, 1))), 404, "not_found")
    assert snapshot() == before


def test_a_technician_elsewhere_is_only_what_they_are_here(
    loose: list[Vial], tree: Tree, other_lab: Lab
) -> None:
    two_labs = member_of(other_lab, Role.TECHNICIAN, "two-labs")
    Membership.objects.create(user=two_labs, lab=tree.box.lab, role=Role.VIEWER)
    before = snapshot()
    assert_problem(post(two_labs, tree.box, body((loose[0], 1, 1))), 403, "permission_denied")
    assert snapshot() == before


@pytest.mark.parametrize(
    ("payload", "code", "attr"),
    [
        ({"placements": []}, "empty", "placements"),
        (
            {"placements": [{"vial": "nope", "row": 1, "col": 1}]},
            "does_not_exist",
            "placements.0.vial",
        ),
        ({"placements": [{"vial": "nope", "row": 27, "col": 1}]}, "max_value", "placements.0.row"),
    ],
    ids=["empty", "unknown vial", "row past Z"],
)
def test_bad_input_names_its_entry(
    payload: dict[str, Any], code: str, attr: str, technician: User, tree: Tree
) -> None:
    before = snapshot()
    problem = assert_problem(post(technician, tree.box, payload), 400, "invalid", attr)
    assert (attr, code) in [(e["attr"], e["code"]) for e in problem["errors"]]
    assert snapshot() == before


def test_a_refusal_on_the_third_vial_names_it_and_places_none(
    technician: User, loose: list[Vial], make_batch: MakeBatch, passage0: Passage, tree: Tree
) -> None:
    make_batch(passage0, vial_count=1, box=tree.box)  # A1
    a, b, c = loose
    before = snapshot()
    response = post(technician, tree.box, body((a, 2, 1), (b, 2, 2), (c, 1, 1)))
    assert_problem(response, 409, "position_taken", "placements.2")
    assert snapshot() == before


# Regulated strains (ADR 0009).


@pytest.fixture
def secret_box(tree: Tree, make_unit: MakeUnit) -> StorageUnit:
    return make_unit(UnitKind.BOX, "Box Hidden", tree.rack, slot=2)


@pytest.fixture
def hidden(regulated: Strain, make_batch: MakeBatch) -> list[Vial]:
    """Two vials of the regulated strain in no box."""
    return vials_of(make_batch(Passage.objects.get(strain=regulated, number=0), vial_count=2))


@pytest.mark.parametrize("granted", [False, True], ids=["without", "with the grant"])
def test_the_answer_carries_no_place_of_a_regulated_vial(
    *, granted: bool, technician: User, keeper: User, hidden: list[Vial], secret_box: StorageUnit
) -> None:
    if granted:
        Membership.objects.filter(user=keeper).update(role=Role.TECHNICIAN)
    writer = keeper if granted else technician
    response = post(writer, secret_box, body((hidden[0], 3, 4), (hidden[1], 3, 5)))
    assert response.status_code == 200, response.content
    text = response.content.decode()
    assert not leaks(text, secret_box), text
    assert '"row"' not in text and '"col"' not in text and "C4" not in text, text
    rows = response.json()["vials"]
    assert [(r["location"], r["location_masked"], r["placed"]) for r in rows] == [
        (None, True, True),
        (None, True, True),
    ]
    assert [r["can_reveal"] for r in rows] == [granted, granted]


def test_refusals_tell_nothing_of_where_a_regulated_vial_is(
    *,
    technician: User,
    hidden: list[Vial],
    loose: list[Vial],
    secret_box: StorageUnit,
    tree: Tree,
) -> None:
    """A regulated vial in a box already, and a position a regulated vial holds: neither answer
    names the box it is in, its position or the vial in the way."""
    post(technician, secret_box, body((hidden[0], 6, 7)))  # where it must stay unnamed
    post(technician, tree.box, body((hidden[1], 2, 2)))  # the vial in the way
    already = post(technician, tree.box, body((loose[0], 1, 1), (hidden[0], 1, 2)))
    assert_problem(already, 409, "vial_already_placed", "placements.1.vial")
    taken = post(technician, tree.box, body((loose[0], 1, 1), (loose[1], 2, 2)))
    assert_problem(taken, 409, "position_taken", "placements.1")
    for response in (already, taken):
        text = response.content.decode()
        assert not leaks(text, secret_box), text
        assert "G7" not in text and '"row"' not in text and '"col"' not in text, text
        for vial in hidden:
            assert not any(part in text for part in identities(vial)), text


# Queries.


@pytest.mark.parametrize("count", [1, 20])
def test_the_place_action_query_count_is_exact_and_flat(
    *,
    count: int,
    technician: User,
    make_batch: MakeBatch,
    passage0: Passage,
    tree: Tree,
    query_baseline: QueryBaseline,
) -> None:
    vials = vials_of(make_batch(passage0, vial_count=count))
    payload = body(*[(v, 1 + i // 9, 1 + i % 9) for i, v in enumerate(vials)])
    client = logged_in(technician)
    with query_baseline("box_place"):
        response = client.post(
            f"{BOXES_URL}{tree.box.public_id}/place/", payload, content_type="application/json"
        )
    assert response.status_code == 200, response.content
    assert len(response.json()["vials"]) == count

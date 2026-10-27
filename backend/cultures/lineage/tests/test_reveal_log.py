"""The reveal log of a lab (#83, ADR 0009): who revealed where a regulated vial is, which vial
and when, read by the lab's managers only and never with the place. LabViewSet's contract class
(labs/tests/test_contract.py) covers the viewset; these tests cover the action."""

from datetime import UTC, datetime
from typing import Any

import pytest

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel
from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.labs import services as labs
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import LAB_URL, member_of, membership
from cultures.lineage.models import Passage, Vial
from cultures.lineage.services import vial_reveal_location
from cultures.storage.models import StorageUnit, UnitKind
from cultures.storage.tests.conftest import MakeUnit, Tree
from cultures.strains.models import Strain
from cultures.users import services as users
from cultures.users.models import User

from .support import MakeBatch, vials_of

pytestmark = pytest.mark.django_db
REVEALS_URL = f"{LAB_URL}reveals/"
# What a reveal row holds, and nothing else: no location, box, path or position.
ROW_KEYS = {"occurred_at", "person", "vial", "vial_label", "strain", "accession_number"}
PERSON_KEYS = {"public_id", "username", "first_name", "last_name", "erased"}
PLACE_KEYS = {"location", "box", "box_name", "path", "row", "col", "label", "position", "placement"}


@pytest.fixture
def secret_box(tree: Tree, make_unit: MakeUnit) -> StorageUnit:
    """A box only regulated vials are in: its name and id must never reach the log."""
    return make_unit(UnitKind.BOX, "Box Hidden", tree.rack, slot=2)


@pytest.fixture
def masked(regulated: Strain, make_batch: MakeBatch, secret_box: StorageUnit) -> list[Vial]:
    passage = Passage.objects.get(strain=regulated, number=0)
    return vials_of(make_batch(passage, vial_count=2, box=secret_box))


@pytest.fixture
def holder(lab: Lab, manager: User) -> User:
    """A technician with the lab's location grant: the person whose reveals the log lists."""
    user = member_of(lab, Role.TECHNICIAN, "holder", first_name="Hana", last_name="Holá")
    grant(lab, manager, user)
    return user


def grant(lab: Lab, manager: User, user: User) -> None:
    with audit_context(channel=Channel.API, actor=manager, request_id="req-grant"):
        labs.location_grant_add(
            access=access_for(manager), lab=lab, membership=membership(user, lab), reason="register"
        )


def reveal(user: User, vial: Vial) -> AuditEvent:
    """A reveal through the service, as a request of the user makes it. Its time is the test
    transaction's: every event of one test has the same occurred_at."""
    with audit_context(channel=Channel.API, actor=user, request_id="req-reveal"):
        vial_reveal_location(access=access_for(user), vial=vial)
    event: AuditEvent = AuditEvent.objects.order_by("-pk")[0]
    return event


def reveal_at(user: User, vial: Vial, at: datetime, lab: Lab | None = None) -> AuditEvent:
    """The event a reveal writes, at a given moment: the database stamps the transaction's time,
    which a test cannot move. test_reveal_at_writes_what_the_service_writes holds it to the
    service's event."""
    event: AuditEvent = AuditEvent.objects.create(
        occurred_at=at,
        event_type="vial_location_revealed",
        actor=user,
        actor_label=f"user:{user.public_id}",
        actor_kind=ActorKind.USER,
        lab_id=vial.lab_id if lab is None else lab.pk,
        strain_id=vial.batch.strain.public_id,
        channel=Channel.API,
        request_id="req-reveal",
        subject_type="vial",
        subject_id=vial.public_id,
    )
    return event


FIELDS = (
    *("event_type", "actor", "actor_label", "actor_kind", "lab", "strain_id", "channel"),
    *("request_id", "batch_id", "reason", "subject_type", "subject_id", "changes"),
)


def test_reveal_at_writes_what_the_service_writes(holder: User, masked: list[Vial]) -> None:
    made = reveal(holder, masked[0])
    copied = reveal_at(holder, masked[0], datetime(2026, 6, 10, tzinfo=UTC))
    assert [getattr(copied, f) for f in FIELDS] == [getattr(made, f) for f in FIELDS]


def page(user: User, query: str = "") -> dict[str, Any]:
    response = logged_in(user).get(f"{REVEALS_URL}{query}")
    assert response.status_code == 200, response.content
    body: dict[str, Any] = response.json()
    return body


def keys_in(value: Any) -> set[str]:
    """Every key of every object anywhere in a JSON value."""
    if isinstance(value, dict):
        return set(value) | set().union(*(keys_in(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(keys_in(v) for v in value))
    return set()


def test_a_manager_reads_who_revealed_which_vial_and_when(
    holder: User, manager: User, masked: list[Vial], regulated: Strain
) -> None:
    event = reveal(holder, masked[1])
    body = page(manager)
    assert body["count"] == 1
    (row,) = body["results"]
    assert row == {
        "occurred_at": event.occurred_at.isoformat().replace("+00:00", "Z"),
        "person": {
            "public_id": str(holder.public_id),
            "username": "holder",
            "first_name": "Hana",
            "last_name": "Holá",
            "erased": False,
        },
        "vial": str(masked[1].public_id),
        "vial_label": f"{regulated.accession_number} / {masked[1].batch.number} / 2",
        "strain": str(regulated.public_id),
        "accession_number": regulated.accession_number,
    }


def test_the_answer_holds_no_location_anywhere(
    holder: User, manager: User, masked: list[Vial], secret_box: StorageUnit, tree: Tree
) -> None:
    reveal(holder, masked[0])
    reveal(holder, masked[1])
    response = logged_in(manager).get(REVEALS_URL)
    body = response.json()
    assert len(body["results"]) == 2
    assert {key for row in body["results"] for key in row} == ROW_KEYS
    assert not keys_in(body) & PLACE_KEYS
    text = response.content.decode()
    # Whole values only: a short position label could be part of a UUID.
    for value in (
        str(secret_box.public_id),
        secret_box.name,
        str(tree.rack.public_id),
        tree.rack.name,
        str(tree.freezer.public_id),
        tree.freezer.name,
    ):
        assert value not in text, value


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_only_managers_read_the_log(role: Role, team: dict[Role, User], manager: User) -> None:
    assert logged_in(manager).get(REVEALS_URL).status_code == 200
    assert_problem(logged_in(team[role]).get(REVEALS_URL), 403, "permission_denied")


def test_a_holder_of_the_grant_does_not_read_the_log(holder: User, masked: list[Vial]) -> None:
    reveal(holder, masked[0])
    assert_problem(logged_in(holder).get(REVEALS_URL), 403, "permission_denied")


def test_an_outsider_gets_404_and_anonymous_401(outsider: User, lab: Lab) -> None:
    assert_problem(logged_in(outsider).get(REVEALS_URL), 404, "not_found")
    response = logged_in(None).get(REVEALS_URL)
    assert_problem(response, 401, "not_authenticated")
    assert response.has_header("WWW-Authenticate")


def test_the_log_is_read_only(manager: User) -> None:
    client = logged_in(manager)
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)(REVEALS_URL, {}, content_type="application/json")
        assert response.status_code == 405, method


def test_newest_first_and_only_reveals_of_this_lab(
    holder: User,
    manager: User,
    masked: list[Vial],
    other_lab: Lab,
) -> None:
    Membership.objects.create(user=manager, lab=other_lab, role=Role.MANAGER)
    reveal_at(holder, masked[0], datetime(2026, 6, 1, 8, tzinfo=UTC))
    reveal_at(holder, masked[1], datetime(2026, 6, 3, 8, tzinfo=UTC))
    reveal_at(holder, masked[0], datetime(2026, 6, 2, 8, tzinfo=UTC))
    # The same event in another lab the manager also manages; this lab's other events (the
    # grant, the batch) are there too.
    reveal_at(holder, masked[0], datetime(2026, 6, 4, 8, tzinfo=UTC), lab=other_lab)
    rows = page(manager)["results"]
    assert [(row["occurred_at"][:10], row["vial"]) for row in rows] == [
        ("2026-06-03", str(masked[1].public_id)),
        ("2026-06-02", str(masked[0].public_id)),
        ("2026-06-01", str(masked[0].public_id)),
    ]


def test_a_plain_vial_leaves_no_row(
    manager: User, viewer: User, passage0: Passage, tree: Tree, make_batch: MakeBatch
) -> None:
    plain = vials_of(make_batch(passage0, vial_count=1, box=tree.box))[0]
    reveal(viewer, plain)
    assert page(manager)["count"] == 0


class TestFilters:
    @pytest.fixture(autouse=True)
    def _reveals(self, holder: User, keeper: User, masked: list[Vial]) -> None:
        # Prague is UTC+2 in summer: 22:30 UTC on 31 May is 00:30 on 1 June there.
        reveal_at(holder, masked[0], datetime(2026, 5, 31, 21, 30, tzinfo=UTC))  # 23:30, 31 May
        reveal_at(keeper, masked[0], datetime(2026, 5, 31, 22, 30, tzinfo=UTC))  # 00:30, 1 June
        reveal_at(holder, masked[1], datetime(2026, 6, 30, 21, 59, tzinfo=UTC))  # 23:59, 30 June
        reveal_at(keeper, masked[1], datetime(2026, 6, 30, 22, 0, tzinfo=UTC))  # 00:00, 1 July

    @staticmethod
    def days(manager: User, query: str) -> list[str]:
        return [row["occurred_at"] for row in page(manager, query)["results"]]

    def test_a_month_is_its_czech_days(self, manager: User) -> None:
        assert self.days(manager, "?since=2026-06-01&until=2026-06-30") == [
            "2026-06-30T21:59:00Z",
            "2026-05-31T22:30:00Z",
        ]

    def test_one_end_alone(self, manager: User) -> None:
        assert len(self.days(manager, "?since=2026-07-01")) == 1
        assert self.days(manager, "?until=2026-05-31") == ["2026-05-31T21:30:00Z"]

    def test_by_person(self, manager: User, keeper: User) -> None:
        rows = page(manager, f"?person={keeper.public_id}")["results"]
        assert [row["person"]["username"] for row in rows] == ["keeper", "keeper"]
        both = f"?person={keeper.public_id}&since=2026-06-01&until=2026-06-30"
        assert self.days(manager, both) == ["2026-05-31T22:30:00Z"]

    def test_an_unknown_person_finds_nothing(self, manager: User, outsider: User) -> None:
        assert page(manager, f"?person={outsider.public_id}")["count"] == 0

    @pytest.mark.parametrize(
        ("query", "attr", "field_code"),
        [
            ("?since=2026-06-31", "since", "invalid"),
            ("?until=June", "until", "invalid"),
            ("?person=holder", "person", "invalid"),
            ("?since=2026-06-02&until=2026-06-01", "until", "invalid_range"),
        ],
    )
    def test_a_bad_filter_answers_400(
        self, manager: User, query: str, attr: str, field_code: str
    ) -> None:
        response = logged_in(manager).get(f"{REVEALS_URL}{query}")
        problem = assert_problem(response, 400, "invalid", attr=attr)
        assert [(e["attr"], e["code"]) for e in problem["errors"]] == [(attr, field_code)]


def test_an_erased_person_reads_as_erased(holder: User, manager: User, masked: list[Vial]) -> None:
    reveal(holder, masked[0])
    with audit_context(
        channel=Channel.COMMAND,
        actor_kind=ActorKind.SYSTEM,
        actor_label="command:test",
        reason="erasure request",
    ):
        users.user_erase(user=holder, reason="erasure request")
    (row,) = page(manager)["results"]
    assert row["person"] == {
        "public_id": str(holder.public_id),
        "username": f"erased-{holder.public_id}",
        "first_name": "",
        "last_name": "",
        "erased": True,
    }
    assert "Hana" not in str(row) and "Holá" not in str(row)


@pytest.mark.parametrize("count", [1, 20])  # one key for both sizes: the count must not grow
def test_the_reveal_log_query_count_is_exact_and_flat(
    count: int, holder: User, manager: User, masked: list[Vial], query_baseline: QueryBaseline
) -> None:
    for n in range(count):
        reveal_at(holder, masked[n % 2], datetime(2026, 6, 1 + n, 8, tzinfo=UTC))
    client = logged_in(manager)
    # Session, user, the access object's memberships, the lab, the count, the page.
    with query_baseline("reveal_log") as captured:
        response = client.get(REVEALS_URL)
    assert response.json()["count"] == count
    assert any('"audit_auditevent"."lab_id" IN (' in q["sql"] for q in captured.captured_queries)

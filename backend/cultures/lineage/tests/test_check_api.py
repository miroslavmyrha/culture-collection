"""The check and release API (#17) for every caller: 401 anonymous, 404 outside the lab, 403
for a role without the permission (before the input is read), viewers and up reading,
technicians and up recording and correcting checks, curators and up releasing and holding. A
refused write changes no row and records no event. Then the answers: the problem body of each
refusal, the check as recorded, and exact query counts."""

from dataclasses import dataclass
from typing import Any

import pytest

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.lineage import services
from cultures.lineage.models import Batch, BatchCheck, BatchStatus, Passage, Vial, VialStatus
from cultures.strains.models import Strain
from cultures.users.models import User

from .support import BATCHES_URL, CHECKS_URL, MakeBatch, pass_all, record, snapshot, vials_of

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class Call:
    name: str
    method: str
    url: str  # {batch} and {check} are filled in
    write: bool
    status: int = 200


CALLS = [
    Call("check_list", "get", CHECKS_URL, write=False),
    Call("check_retrieve", "get", CHECKS_URL + "{check}/", write=False),
    Call("record", "post", CHECKS_URL, write=True, status=201),
    Call("enter_in_error", "post", CHECKS_URL + "{check}/enter-in-error/", write=True),
    Call("release", "post", BATCHES_URL + "{batch}/release/", write=True),
    Call("hold", "post", BATCHES_URL + "{batch}/hold/", write=True),
]
# Who may write what: the bench records checks, curators decide.
WRITERS: dict[str, set[Role]] = {
    "record": {Role.TECHNICIAN, Role.CURATOR, Role.MANAGER},
    "enter_in_error": {Role.TECHNICIAN, Role.CURATOR, Role.MANAGER},
    "release": {Role.CURATOR, Role.MANAGER},
    "hold": {Role.CURATOR, Role.MANAGER},
}


@pytest.fixture
def batch(make_batch: MakeBatch, passage0: Passage, technician: User) -> Batch:
    """Two vials, with a passed check of each kind: ready to be released."""
    batch = make_batch(passage0, vial_count=2)
    with audit_context(channel=Channel.API, actor=technician, request_id="req-setup"):
        pass_all(technician, batch)
    return batch


@pytest.fixture
def check(batch: Batch) -> BatchCheck:
    return BatchCheck.objects.filter(batch=batch).order_by("pk").first()  # type: ignore[return-value]


def body(call: Call, batch: Batch) -> dict[str, Any]:
    bodies: dict[str, dict[str, Any]] = {
        "record": {
            "batch": str(batch.public_id),
            "kind": "purity",
            "stage": "periodic",
            "checked_on": "2026-10-05",
            "method": "streak_plate",
            "result": "pass",
            "vial": str(vials_of(batch)[0].public_id),
        },
        "enter_in_error": {"reason": "recorded on the wrong batch"},
        "release": {"reason": "all three checks passed"},
        "hold": {"reason": "a recipient reported a mixed culture"},
    }
    return bodies.get(call.name, {})


def send(user: User | None, call: Call, batch: Batch, check: BatchCheck) -> Any:
    url = call.url.format(batch=batch.public_id, check=check.public_id)
    return getattr(logged_in(user), call.method)(
        url, body(call, batch), content_type="application/json"
    )


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_anonymous_gets_401(call: Call, batch: Batch, check: BatchCheck) -> None:
    before = snapshot()
    assert_problem(send(None, call, batch, check), 401, "not_authenticated")
    assert snapshot() == before


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_a_member_of_another_lab_gets_404_for_everything(
    call: Call, batch: Batch, check: BatchCheck, outsider: User
) -> None:
    before = snapshot()
    assert_problem(send(outsider, call, batch, check), 404, "not_found")
    assert snapshot() == before


@pytest.mark.parametrize("call", [c for c in CALLS if not c.write], ids=lambda c: c.name)
@pytest.mark.parametrize("role", list(Role))
def test_every_role_reads(
    *, call: Call, role: Role, batch: Batch, check: BatchCheck, team: dict[Role, User]
) -> None:
    assert send(team[role], call, batch, check).status_code == 200


WRITES = [(c, r) for c in CALLS if c.write for r in Role]


@pytest.mark.parametrize(("call", "role"), WRITES, ids=lambda x: getattr(x, "name", x))
def test_each_role_writes_exactly_what_it_may(
    *, call: Call, role: Role, batch: Batch, check: BatchCheck, team: dict[Role, User]
) -> None:
    before = snapshot()
    events = AuditEvent.objects.count()
    response = send(team[role], call, batch, check)
    if role in WRITERS[call.name]:
        assert response.status_code == call.status, response.content
        assert snapshot() != before
        assert AuditEvent.objects.count() > events
    else:
        assert_problem(response, 403, "permission_denied")
        assert snapshot() == before
        assert AuditEvent.objects.count() == events


@pytest.mark.parametrize("call", [c for c in CALLS if c.write], ids=lambda c: c.name)
def test_a_viewer_gets_403_before_the_input_is_read(
    call: Call, batch: Batch, check: BatchCheck, viewer: User
) -> None:
    before = snapshot()
    url = call.url.format(batch=batch.public_id, check=check.public_id)
    response = logged_in(viewer).post(
        url, {"batch": "x", "kind": "x", "reason": ""}, content_type="application/json"
    )
    assert_problem(response, 403, "permission_denied")
    assert snapshot() == before


def test_outside_the_lab_invalid_input_is_still_404(outsider: User) -> None:
    response = logged_in(outsider).post(CHECKS_URL, {"batch": "x"}, content_type="application/json")
    assert_problem(response, 404, "not_found")


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_a_check_is_never_changed_in_place_or_deleted(
    method: str, check: BatchCheck, manager: User
) -> None:
    response = getattr(logged_in(manager), method)(
        f"{CHECKS_URL}{check.public_id}/", {}, content_type="application/json"
    )
    assert_problem(response, 405, "method_not_allowed")


def test_a_technician_elsewhere_is_only_a_viewer_here(
    batch: Batch, check: BatchCheck, other_lab: Lab
) -> None:
    two_labs = member_of(other_lab, Role.CURATOR, "two-labs")
    Membership.objects.create(user=two_labs, lab=batch.lab, role=Role.VIEWER)
    for call in CALLS:
        if call.write:
            assert_problem(send(two_labs, call, batch, check), 403, "permission_denied")


def test_a_batch_of_another_lab_is_unknown_here(
    batch: Batch, technician: User, other_lab: Lab, make_batch: MakeBatch
) -> None:
    """The batch field resolves batches of every lab where the caller handles vials; the view
    keeps the lab of the URL, with the same message as an unknown id."""
    Membership.objects.create(user=technician, lab=other_lab, role=Role.TECHNICIAN)
    other_url = f"/api/v1/labs/{other_lab.public_id}/batch-checks/"
    before = snapshot()
    response = logged_in(technician).post(
        other_url, body(CALLS[2], batch), content_type="application/json"
    )
    assert_problem(response, 400, "does_not_exist", "batch")
    assert snapshot() == before


# The answers.


def test_a_recorded_check_comes_back_whole(batch: Batch, technician: User, strain: Strain) -> None:
    vial = vials_of(batch)[0]
    response = logged_in(technician).post(
        CHECKS_URL,
        {
            "batch": str(batch.public_id),
            "kind": "viability",
            "stage": "periodic",
            "checked_on": "2026-10-05",
            "method": "plate_count",
            "method_detail": "TSA, 30 °C, 48 h",
            "result": "reduced",
            "value": "1.5e7",
            "unit": "cfu_per_ml",
            "vial": str(vial.public_id),
            "note": "A tenth of the count at preservation.",
        },
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    check = BatchCheck.objects.get(public_id=response.json()["public_id"])
    assert response.json() == {
        "public_id": str(check.public_id),
        "batch": str(batch.public_id),
        "batch_number": 1,
        "kind": "viability",
        "stage": "periodic",
        "checked_on": "2026-10-05",
        "performed_by": "technician",
        "method": "plate_count",
        "method_detail": "TSA, 30 °C, 48 h",
        "result": "reduced",
        "value": "15000000.0000",
        "unit": "cfu_per_ml",
        "vial": str(vial.public_id),
        "vial_label": f"{strain.accession_number} / 1 / 1",
        "note": "A tenth of the count at preservation.",
        "status": "valid",
        "supersedes": None,
        "reason": "",
        "created_at": response.json()["created_at"],
    }
    assert Vial.objects.get(pk=vial.pk).status == VialStatus.CONSUMED


def test_a_release_answers_the_batch_with_its_checks(batch: Batch, curator: User) -> None:
    response = logged_in(curator).post(
        f"{BATCHES_URL}{batch.public_id}/release/",
        {"reason": "all three checks passed"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    answer = response.json()
    assert (answer["status"], answer["status_reason"]) == ("released", "all three checks passed")
    assert answer["status_changed_at"] is not None
    assert answer["latest_checks"] == {"identity": "pass", "purity": "pass", "viability": "pass"}
    assert (answer["vials_available"], answer["vials_distributable"]) == (2, 2)


@pytest.mark.parametrize(
    ("changes", "code", "attr"),
    [
        ({"method": "growth"}, "invalid", "method"),  # a viability method on a purity check
        ({"value": "3"}, "required", "unit"),
        ({"unit": "percent"}, "required", "value"),
        ({"value": "101", "unit": "percent"}, "invalid", "value"),
        ({"result": "reduced"}, "required", "note"),
        ({"method": "other"}, "required", "method_detail"),
        ({"checked_on": "2026-09-01"}, "invalid", "checked_on"),
        ({"vial": "00000000-0000-4000-8000-000000000000"}, "does_not_exist", "vial"),
        ({"supersedes": "00000000-0000-4000-8000-000000000000"}, "does_not_exist", "supersedes"),
        ({"kind": "smell"}, "invalid_choice", "kind"),
        ({"unit": "litres", "value": "1"}, "invalid_choice", "unit"),
        ({"value": "1.00001", "unit": "percent"}, "max_decimal_places", "value"),
    ],
)
def test_a_refused_check_names_its_field(
    *, batch: Batch, technician: User, changes: dict[str, Any], code: str, attr: str
) -> None:
    before = snapshot()
    payload = {**body(CALLS[2], batch), **changes}
    response = logged_in(technician).post(CHECKS_URL, payload, content_type="application/json")
    problem = assert_problem(response, 400, response.json()["code"], attr)
    assert problem["code"] in (code, "invalid")  # a service error, or the serializer's
    assert [(e["attr"], e["code"]) for e in problem["errors"]] == [(attr, code)]
    assert snapshot() == before


def test_the_conflicts_and_rules_have_their_codes(
    batch: Batch, check: BatchCheck, technician: User, curator: User, make_batch: MakeBatch
) -> None:
    tech, cur = logged_in(technician), logged_in(curator)
    vial = vials_of(batch)[0]
    with audit_context(channel=Channel.API, actor=technician, request_id="req-setup"):
        services.vial_revive(access=access_for(technician), vial=vial)
    payload = body(CALLS[2], batch)
    assert_problem(
        tech.post(CHECKS_URL, payload, content_type="application/json"), 409, "vial_not_available"
    )
    error_url = f"{CHECKS_URL}{check.public_id}/enter-in-error/"
    first = tech.post(error_url, {"reason": "mix-up"}, content_type="application/json")
    assert first.status_code == 200, first.content
    assert_problem(
        tech.post(error_url, {"reason": "again"}, content_type="application/json"),
        409,
        "check_entered_in_error",
    )
    assert_problem(
        cur.post(
            f"{BATCHES_URL}{batch.public_id}/release/",
            {"reason": "ok"},
            content_type="application/json",
        ),
        422,
        "checks_not_passed",
    )
    assert_problem(
        cur.post(
            f"{BATCHES_URL}{batch.public_id}/hold/", {"reason": ""}, content_type="application/json"
        ),
        400,
        "invalid",
        "reason",
    )
    valid = BatchCheck.objects.filter(batch=batch, status="valid").order_by("pk").first()
    assert valid is not None
    assert_problem(
        tech.post(
            f"{CHECKS_URL}{valid.public_id}/enter-in-error/",
            {"reason": "  "},  # trimmed to nothing
            content_type="application/json",
        ),
        400,
        "invalid",
        "reason",
    )
    other = make_batch(batch.passage, vial_count=1)
    Batch.objects.filter(pk=other.pk).update(
        status=BatchStatus.EXHAUSTED, status_reason="sent", status_changed_at=other.created_at
    )
    assert_problem(
        cur.post(
            f"{BATCHES_URL}{other.public_id}/hold/",
            {"reason": "a doubt"},
            content_type="application/json",
        ),
        409,
        "batch_exhausted",
    )


def test_the_check_list_filters_by_batch_and_shows_entered_in_error(
    batch: Batch, check: BatchCheck, technician: User, viewer: User, make_batch: MakeBatch
) -> None:
    other = make_batch(batch.passage, vial_count=1)
    with audit_context(channel=Channel.API, actor=technician, request_id="req-setup"):
        record(technician, other)
        services.check_enter_in_error(access=access_for(technician), check=check, reason="mix-up")
    client = logged_in(viewer)
    rows = client.get(CHECKS_URL, {"batch": str(batch.public_id)}).json()["results"]
    assert len(rows) == 3
    assert {r["batch"] for r in rows} == {str(batch.public_id)}
    wrong = next(r for r in rows if r["public_id"] == str(check.public_id))
    assert (wrong["status"], wrong["reason"]) == ("entered_in_error", "mix-up")
    assert client.get(CHECKS_URL, {"strain": str(batch.strain.public_id)}).json()["count"] == 4
    assert_problem(client.get(CHECKS_URL, {"batch": "nope"}), 400, "invalid", "batch")


def scoped(queries: list[dict[str, Any]], table: str) -> bool:
    return any(f'FROM "{table}"' in q["sql"] and '"lab_id" IN' in q["sql"] for q in queries)


@pytest.mark.parametrize("checks", [1, 20])
def test_the_check_list_query_count_is_exact_and_flat(
    *,
    checks: int,
    viewer: User,
    technician: User,
    passage0: Passage,
    make_batch: MakeBatch,
    query_baseline: QueryBaseline,
) -> None:
    batch = make_batch(passage0, vial_count=checks)
    with audit_context(channel=Channel.API, actor=technician, request_id="req-setup"):
        for vial in vials_of(batch):
            record(technician, batch, vial=vial)
    client = logged_in(viewer)
    # Session, user, memberships, the lab, the count and the page with batch, strain, person,
    # vial and corrected check joined.
    with query_baseline("check_list") as captured:
        assert client.get(CHECKS_URL).json()["count"] == checks
    assert scoped(captured.captured_queries, "lineage_batchcheck")


@pytest.mark.parametrize("batches", [1, 20])
def test_the_batch_list_with_checks_stays_flat(
    *,
    batches: int,
    viewer: User,
    technician: User,
    passage0: Passage,
    make_batch: MakeBatch,
    query_baseline: QueryBaseline,
) -> None:
    with audit_context(channel=Channel.API, actor=technician, request_id="req-setup"):
        for _ in range(batches):
            pass_all(technician, make_batch(passage0, vial_count=1))
    client = logged_in(viewer)
    with query_baseline("batch_list"):
        rows = client.get(BATCHES_URL).json()["results"]
    assert {r["latest_checks"]["purity"] for r in rows} == {"pass"}

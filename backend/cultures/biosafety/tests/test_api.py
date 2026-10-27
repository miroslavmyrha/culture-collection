"""The lab's permits as managers read them (#82): who may read, where each permit stands on the
Czech day, the order, and an exact flat query count. The shared matrix is TestPermitContract."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import time_machine

from cultures.biosafety.api.views import PermitViewSet
from cultures.biosafety.models import AuthorisationKind, LabAuthorisation
from cultures.biosafety.policy import EXPIRES_SOON_DAYS
from cultures.core.testing import QueryBaseline, ViewsetContract, assert_problem, logged_in
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import LAB_URL
from cultures.users.models import User

from .support import make_permit

pytestmark = pytest.mark.django_db
PERMITS_URL = f"{LAB_URL}permits/"
# 10:00 UTC is noon in Prague: the same day in both.
TODAY = date(2026, 6, 15)
QUARANTINE = AuthorisationKind.QUARANTINE_PEST


@pytest.fixture(autouse=True)
def _today() -> Iterator[None]:
    with time_machine.travel(datetime(2026, 6, 15, 10, tzinfo=UTC), tick=False):
        yield


def days(n: int) -> date:
    return TODAY + timedelta(days=n)


def permit(lab: Lab, reference: str, **fields: Any) -> LabAuthorisation:
    values: dict[str, Any] = {"valid_from": date(2026, 1, 1), "expires_on": None, **fields}
    return make_permit(lab, permit_reference=reference, **values)


def rows(user: User, url: str = PERMITS_URL) -> list[dict[str, Any]]:
    response = logged_in(user).get(url)
    assert response.status_code == 200, response.content
    listed: list[dict[str, Any]] = response.json()
    return listed


def by_reference(user: User) -> dict[str, dict[str, Any]]:
    return {row["permit_reference"]: row for row in rows(user)}


class TestPermitContract(ViewsetContract):
    """Only managers read permits and nobody writes them here, so the reader is the manager;
    the refusals per role are in test_only_managers_read_the_permits."""

    viewset = PermitViewSet
    url = PERMITS_URL
    writes = ()  # staff record and end permits in Django admin only

    @pytest.fixture
    def obj(self, lab: Lab) -> LabAuthorisation:
        return permit(lab, "SÚJB/DEV/1")

    @pytest.fixture
    def reader(self, manager: User) -> User:
        return manager

    @pytest.fixture
    def writer(self, manager: User) -> User:
        return manager

    # Not paged, and nested under a lab the outsider is not in: the whole list answers 404.
    def test_list_is_scoped(self, obj: LabAuthorisation, reader: User, outsider: User) -> None:
        assert str(obj.public_id) in [row["public_id"] for row in rows(reader)]
        assert_problem(logged_in(outsider).get(self.url), 404, "not_found")


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_only_managers_read_the_permits(
    role: Role, team: dict[Role, User], lab: Lab, manager: User
) -> None:
    held = permit(lab, "SÚJB/DEV/1")
    detail = f"{PERMITS_URL}{held.public_id}/"
    assert logged_in(manager).get(detail).status_code == 200
    assert_problem(logged_in(team[role]).get(PERMITS_URL), 403, "permission_denied")
    # The rows are scoped by the permission too: a single permit is not found, as a deposit is
    # not for a viewer.
    assert_problem(logged_in(team[role]).get(detail), 404, "not_found")


def test_the_screen_writes_nothing(lab: Lab, manager: User) -> None:
    held = permit(lab, "SÚJB/DEV/1")
    client = logged_in(manager)
    assert client.post(PERMITS_URL, {}, content_type="application/json").status_code == 405
    for method in ("put", "patch", "delete"):
        response = getattr(client, method)(
            f"{PERMITS_URL}{held.public_id}/", {}, content_type="application/json"
        )
        assert response.status_code == 405, method
    assert LabAuthorisation.objects.get(pk=held.pk).ended_on is None


def test_a_manager_of_two_labs_sees_only_this_labs_permits(
    lab: Lab, other_lab: Lab, manager: User
) -> None:
    Membership.objects.create(user=manager, lab=other_lab, role=Role.MANAGER)
    permit(lab, "SÚJB/DEV/MYC")
    permit(other_lab, "SÚJB/DEV/BAC")
    assert [row["permit_reference"] for row in rows(manager)] == ["SÚJB/DEV/MYC"]


def test_a_row_says_what_the_permit_is_in_words(lab: Lab, manager: User) -> None:
    permit(lab, "ÚKZÚZ/DEV/1", kind=QUARANTINE, expires_on=date(2027, 12, 31))
    (row,) = rows(manager)
    assert row["kind"] == "quarantine_pest"
    assert row["kind_label"] == "Permit to hold quarantine pests"
    assert row["issuer"] == "ukzuz"
    assert row["issuer_label"] == "ÚKZÚZ"
    assert row["valid_from"] == "2026-01-01"
    assert row["expires_on"] == "2027-12-31"
    assert row["ended_on"] is None
    assert row["end_reason"] == ""


# (fields, standing, last valid day, days left) on TODAY; EXPIRES_SOON_DAYS is 30. An end
# recorded ahead counts like an expiry on the day before it.
SOON = EXPIRES_SOON_DAYS
STANDINGS = [
    ({}, "valid", None, None),
    ({"expires_on": days(SOON + 1)}, "valid", days(31), 31),
    ({"expires_on": days(SOON)}, "expires_soon", days(30), 30),
    ({"expires_on": TODAY}, "expires_soon", TODAY, 0),
    ({"expires_on": days(-1)}, "expired", days(-1), None),
    ({"ended_on": days(SOON + 2), "end_reason": "Surrendered"}, "valid", days(31), 31),
    ({"ended_on": days(SOON + 1), "end_reason": "Surrendered"}, "expires_soon", days(30), 30),
    ({"ended_on": TODAY, "end_reason": "Revoked"}, "ended", days(-1), None),
    ({"expires_on": days(10), "ended_on": days(-5), "end_reason": "x"}, "ended", days(-6), None),
    ({"valid_from": days(1), "expires_on": days(5)}, "not_yet_valid", days(5), None),
]


@pytest.mark.parametrize("case", STANDINGS)
def test_each_permit_says_where_it_stands_today(
    case: tuple[dict[str, Any], str, date | None, int | None], lab: Lab, manager: User
) -> None:
    fields, standing, last, left = case
    permit(lab, "SÚJB/DEV/1", **fields)
    (row,) = rows(manager)
    assert row["standing"] == standing
    assert row["last_valid_day"] == (last and last.isoformat())
    assert row["days_left"] == left


def test_the_day_is_the_czech_one(lab: Lab, manager: User) -> None:
    # 22:30 UTC on 15 June is 00:30 on 16 June in Prague (summer time): the 15th is past.
    permit(lab, "SÚJB/DEV/1", expires_on=TODAY)
    with time_machine.travel(datetime(2026, 6, 15, 22, 30, tzinfo=UTC), tick=False):
        (row,) = rows(manager)
    assert row["standing"] == "expired"


def test_what_expires_soon_comes_first_and_the_history_last(lab: Lab, manager: User) -> None:
    permit(lab, "ended-long-ago", valid_from=days(-900), ended_on=days(-300), end_reason="Revoked")
    permit(lab, "valid-no-expiry")
    permit(lab, "expired-lately", expires_on=days(-2))
    permit(lab, "valid-later", expires_on=days(200))
    permit(lab, "soon-second", expires_on=days(20))
    permit(lab, "starts-later", valid_from=days(3), expires_on=days(900))
    permit(lab, "soon-first", kind=QUARANTINE, expires_on=days(3))
    permit(lab, "valid-sooner", expires_on=days(100))
    assert [row["permit_reference"] for row in rows(manager)] == [
        "soon-first",
        "soon-second",
        "valid-sooner",
        "valid-later",
        "valid-no-expiry",
        "starts-later",
        "expired-lately",
        "ended-long-ago",
    ]


def test_an_empty_lab_lists_nothing(lab: Lab, manager: User) -> None:
    assert rows(manager) == []


@pytest.mark.parametrize("count", [1, 20])  # one key for both sizes: the count must not grow
def test_the_permit_list_query_count_is_exact_and_flat(
    count: int, lab: Lab, other_lab: Lab, manager: User, query_baseline: QueryBaseline
) -> None:
    for n in range(count):
        permit(lab, f"SÚJB/DEV/{n}", expires_on=days(n * 5))
    permit(other_lab, "SÚJB/DEV/other")
    client = logged_in(manager)
    # Session, user, the access object's memberships, the lab, the permits.
    with query_baseline("permit_list") as captured:
        response = client.get(PERMITS_URL)
    assert len(response.json()) == count
    scoped = [
        q["sql"]
        for q in captured.captured_queries
        if '"biosafety_labauthorisation"."lab_id" IN (' in q["sql"]
    ]
    assert scoped

"""Exact, flat query counts for both lists, with the lab scope visible in the SQL.

A count cannot see a lost scope (the same number of queries can return other
labs' rows), so each test also finds the scoping condition in the captured SQL.
"""

import pytest

from cultures.core.testing import QueryBaseline, logged_in
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.users.models import User

from .conftest import LABS_URL, MEMBERS_URL, make_lab, make_user

pytestmark = pytest.mark.django_db


def scoped_sql(queries: list[dict[str, str]], table: str, column: str) -> list[str]:
    return [q["sql"] for q in queries if f'"{table}"."{column}" IN (' in q["sql"]]


@pytest.mark.parametrize("rows", [1, 20])  # one key for both sizes: the count must not grow
def test_the_lab_list_query_count_is_exact_and_flat(
    rows: int, stranger: User, other_lab: Lab, query_baseline: QueryBaseline
) -> None:
    for _ in range(rows):
        Membership.objects.create(user=stranger, lab=make_lab(), role=Role.CURATOR)
    client = logged_in(stranger)  # log in outside the counted block: only the request counts
    # Session, user, the access object's memberships, count, page with the role subquery.
    with query_baseline("lab_list") as captured:
        response = client.get(LABS_URL)
    assert response.json()["count"] == rows
    assert scoped_sql(captured.captured_queries, "labs_lab", "id")
    assert str(other_lab.public_id) not in {row["public_id"] for row in response.json()["results"]}


@pytest.mark.parametrize("rows", [1, 20])
def test_the_member_list_query_count_is_exact_and_flat(
    rows: int, lab: Lab, manager: User, query_baseline: QueryBaseline
) -> None:
    for i in range(rows - 1):
        Membership.objects.create(user=make_user(f"member-{i:02}"), lab=lab, role=Role.VIEWER)
    client = logged_in(manager)
    # Session, user, memberships, the lab, count, page with the users joined.
    with query_baseline("member_list") as captured:
        response = client.get(MEMBERS_URL)
    assert response.json()["count"] == rows
    assert scoped_sql(captured.captured_queries, "labs_membership", "lab_id")


def test_member_pages_neither_repeat_nor_skip(lab: Lab, manager: User) -> None:
    client = logged_in(manager)
    for i in range(4):
        Membership.objects.create(user=make_user(f"m{i}"), lab=lab, role=Role.VIEWER)
    pages = [client.get(MEMBERS_URL, {"limit": 2, "offset": n}).json() for n in (0, 2, 4)]
    seen = [row["username"] for page in pages for row in page["results"]]
    assert seen == ["m0", "m1", "m2", "m3", "manager"]

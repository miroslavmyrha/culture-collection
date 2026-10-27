"""The media API and the growth fields of the strain and passage APIs (#79): the contract
matrix, who may do what, the shape of the output, and flat query counts. The per-role matrix of
the strain's growth action is in strains/tests/test_api_permissions.py and of the revival in
lineage/tests/test_api.py."""

from collections.abc import Callable
from typing import Any

import pytest

from cultures.audit.models import AuditEvent
from cultures.core.testing import QueryBaseline, ViewsetContract, Write, assert_problem, logged_in
from cultures.growth.api.views import MediumViewSet
from cultures.growth.models import GrowthMedium
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.strains.models import Strain
from cultures.strains.tests.conftest import LAB_ID, STRAINS_URL
from cultures.strains.tests.test_api import field_code
from cultures.users.models import User

from .conftest import MakeMedium

pytestmark = pytest.mark.django_db
MEDIA_URL = f"/api/v1/labs/{LAB_ID}/media/"
V, T, C, M = Role.VIEWER, Role.TECHNICIAN, Role.CURATOR, Role.MANAGER


def send(user: User | None, method: str, url: str, body: dict[str, Any] | None = None) -> Any:
    return getattr(logged_in(user), method)(url, body or {}, content_type="application/json")


class TestMediumContract(ViewsetContract):
    viewset = MediumViewSet
    url = MEDIA_URL
    audit_model = AuditEvent
    writes = (
        Write(
            "",
            {"name": "Renamed", "composition_reference": "DSMZ 1"},
            changes=GrowthMedium,
            method="put",
            status=200,
        ),
        Write("retire/", {"reason": "Withdrawn"}, changes=GrowthMedium, status=200),
    )

    @pytest.fixture
    def obj(self, make_medium: MakeMedium) -> GrowthMedium:
        return make_medium()

    @pytest.fixture
    def reader(self, viewer: User) -> User:
        return viewer

    @pytest.fixture
    def writer(self, curator: User) -> User:
        return curator

    # The list is nested under a lab the outsider is not a member of: the whole list is a 404.
    def test_list_is_scoped(self, obj: Any, reader: User, outsider: User) -> None:
        listed = logged_in(reader).get(self.url).json()["results"]
        assert str(obj.public_id) in [row["public_id"] for row in listed]
        assert_problem(logged_in(outsider).get(self.url), 404, "not_found")


# Who may do what.


@pytest.mark.parametrize("role", [V, T, C, M])
def test_every_member_reads_the_list_and_a_medium(
    role: Role, team: dict[Role, User], make_medium: MakeMedium
) -> None:
    medium = make_medium("Marine broth", composition_reference="DSMZ 514")
    listed = send(team[role], "get", MEDIA_URL).json()["results"]
    assert [m["name"] for m in listed] == ["Marine broth"]
    one = send(team[role], "get", f"{MEDIA_URL}{medium.public_id}/").json()
    assert (one["composition_reference"], one["retired_at"]) == ("DSMZ 514", None)


@pytest.mark.parametrize("role", [V, T, C, M])
@pytest.mark.parametrize("action", ["create", "update", "retire"])
def test_only_curators_and_managers_write_media(
    role: Role, action: str, team: dict[Role, User], make_medium: MakeMedium
) -> None:
    medium = make_medium()
    detail = f"{MEDIA_URL}{medium.public_id}/"
    call = {
        "create": ("post", MEDIA_URL, {"name": "Agar"}),
        "update": ("put", detail, {"name": "Renamed"}),
        "retire": ("post", f"{detail}retire/", {"reason": "Withdrawn"}),
    }[action]
    events = AuditEvent.objects.count()
    response = send(team[role], *call)
    if role in (C, M):
        assert response.status_code in (200, 201), response.content
        assert AuditEvent.objects.count() == events + 1
    else:
        assert_problem(response, 403, "permission_denied")
        assert AuditEvent.objects.count() == events


def test_invalid_input_from_a_technician_is_403_not_400(technician: User) -> None:
    assert_problem(send(technician, "post", MEDIA_URL, {"name": ""}), 403, "permission_denied")


def test_media_are_not_patched_or_deleted(curator: User, make_medium: MakeMedium) -> None:
    detail = f"{MEDIA_URL}{make_medium().public_id}/"
    for method in ("patch", "delete"):
        assert_problem(send(curator, method, detail), 405, "method_not_allowed")


def test_the_media_of_another_lab_are_not_listed(
    curator: User, outsider: User, other_lab: Lab, make_medium: MakeMedium
) -> None:
    make_medium("Mine")
    make_medium("Theirs", lab=other_lab, actor=outsider)
    assert [m["name"] for m in send(curator, "get", MEDIA_URL).json()["results"]] == ["Mine"]


# Errors.


def test_a_taken_name_is_400_on_the_name(curator: User, make_medium: MakeMedium) -> None:
    make_medium("Broth")
    response = send(curator, "post", MEDIA_URL, {"name": "broth"})
    assert field_code(assert_problem(response, 400, "unique", "name"), "name") == "unique"


def test_a_retired_medium_is_409_when_renamed_and_listed_last(
    curator: User, make_medium: MakeMedium
) -> None:
    old = make_medium("A first")
    make_medium("B second")
    detail = f"{MEDIA_URL}{old.public_id}/"
    retired = send(curator, "post", f"{detail}retire/", {"reason": "Withdrawn"}).json()
    assert retired["retired_at"] is not None
    assert_problem(send(curator, "put", detail, {"name": "X"}), 409, "medium_retired")
    assert [m["name"] for m in send(curator, "get", MEDIA_URL).json()["results"]] == [
        "B second",
        "A first",
    ]


# Strain growth.


def test_a_strain_shows_how_it_is_grown_and_the_action_sets_it(
    curator: User, viewer: User, make_strain: Callable[..., Strain], make_medium: MakeMedium
) -> None:
    strain = make_strain()
    medium = make_medium("Nutrient agar", composition_reference="DSMZ 1")
    url = f"{STRAINS_URL}{strain.public_id}/"
    assert send(viewer, "get", url).json()["growth"] == {
        "medium": None,
        "temperature_low_c": None,
        "temperature_high_c": None,
        "atmosphere": "",
    }
    response = send(
        curator,
        "post",
        f"{url}growth/",
        {
            "medium": str(medium.public_id),
            "temperature_low_c": 25,
            "temperature_high_c": 30,
            "atmosphere": "aerobic",
            "reason": "From the sheet",
        },
    )
    assert response.status_code == 200, response.content
    growth = send(viewer, "get", url).json()["growth"]
    assert growth["medium"] == {
        "public_id": str(medium.public_id),
        "name": "Nutrient agar",
        "composition_reference": "DSMZ 1",
        "retired_at": None,
    }
    assert (growth["temperature_low_c"], growth["temperature_high_c"]) == (25, 30)
    assert growth["atmosphere"] == "aerobic"


@pytest.mark.parametrize(
    ("body", "attr", "code"),
    [
        ({"temperature_low_c": 300}, "temperature_low_c", "invalid"),
        ({"temperature_high_c": 30}, "temperature_low_c", "invalid"),
        ({"temperature_low_c": 30, "temperature_high_c": 20}, "temperature_high_c", "invalid"),
        ({"atmosphere": "martian"}, "atmosphere", "invalid_choice"),
        ({"medium": "00000000-0000-4000-8000-000000000999"}, "medium", "does_not_exist"),
        ({"reason": ""}, "reason", "blank"),
    ],
)
def test_impossible_growth_is_400_on_its_field(
    body: dict[str, Any],
    attr: str,
    code: str,
    curator: User,
    make_strain: Callable[..., Strain],
) -> None:
    strain = make_strain()
    response = send(
        curator, "post", f"{STRAINS_URL}{strain.public_id}/growth/", {"reason": "r", **body}
    )
    body = assert_problem(response, 400, "invalid", attr)
    assert field_code(body, attr) == code


def test_a_medium_of_another_lab_is_not_found_by_id(
    curator: User,
    outsider: User,
    other_lab: Lab,
    make_strain: Callable[..., Strain],
    make_medium: MakeMedium,
) -> None:
    strain = make_strain()
    foreign = make_medium("Theirs", lab=other_lab, actor=outsider)
    response = send(
        curator,
        "post",
        f"{STRAINS_URL}{strain.public_id}/growth/",
        {"medium": str(foreign.public_id), "reason": "r"},
    )
    body = assert_problem(response, 400, "invalid", "medium")
    assert field_code(body, "medium") == "does_not_exist"


# Query counts.


@pytest.mark.parametrize("rows", [1, 20])
def test_the_media_list_query_count_is_exact_and_flat(
    rows: int, curator: User, make_medium: MakeMedium, query_baseline: QueryBaseline
) -> None:
    for i in range(rows):
        make_medium(f"Medium {i}")
    client = logged_in(curator)
    with query_baseline("medium_list"):
        assert client.get(MEDIA_URL).json()["count"] == rows

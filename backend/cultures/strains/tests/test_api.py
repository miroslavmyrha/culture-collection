"""What the strain API answers: the bodies, the server errors a form maps onto its fields,
the filters (in scope, 400 for unknown values), the order and the exact query counts."""

from typing import Any

import pytest

from cultures.audit.models import AuditEvent
from cultures.biosafety.models import RestrictionKind
from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.labs.models import Lab
from cultures.strains.models import Pathogenicity, Strain, StrainRestriction
from cultures.strains.services import RestrictionInput
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .conftest import DUAL_USE, GMO, STRAINS_URL, MakeStrain, end_restriction

pytestmark = pytest.mark.django_db
# Raised by the services with their own code on top; a serializer's field error is "invalid".
DOMAIN_CODES = {"risk_group_4_refused", "lab_authorisation_required", "unique"}


def payload(of: Taxon, **changes: Any) -> dict[str, Any]:
    return {
        "taxon": str(of.public_id),
        "name_as_received": "Testella exempli T1",
        "identified_on": "2026-01-10",
        "identification_method": "16S rRNA gene sequence",
        "risk_group": 2,
        "animal_pathogenicity": "none_known",
        "plant_pathogenicity": "pathogenic",
        "isolation_source": "garden soil",
        "country_of_origin": "CZ",
        "isolation_date": "2019-05",
        "restrictions": [
            {"kind": "dual_use", "reference": "1C351.c", "act": "(EU) 2025/2003"},
            {"kind": "gmo", "reference": "MŽP 2026/12", "gmo_category": 2},
        ],
        **changes,
    }


def post(user: User, body: dict[str, Any], path: str = "") -> Any:
    return logged_in(user).post(f"{STRAINS_URL}{path}", body, content_type="application/json")


def test_the_detail_of_a_strain(
    viewer: User, lab: Lab, exempli: Taxon, make_strain: MakeStrain
) -> None:
    make_strain(
        risk_group=2,
        animal_pathogenicity=Pathogenicity.NONE_KNOWN,
        plant_pathogenicity=Pathogenicity.PATHOGENIC,
        isolation_source="garden soil",
        country_of_origin="CZ",
        isolation_date="2019-05",
        restrictions=[
            DUAL_USE,
            RestrictionInput(RestrictionKind.GMO, "MŽP 2026/12", gmo_category=2),
        ],
    )
    events = AuditEvent.objects.count()
    strain = Strain.objects.get()
    response = logged_in(viewer).get(f"{STRAINS_URL}{strain.public_id}/")
    assert response.status_code == 200, response.content
    body = response.json()
    strain = Strain.objects.get()
    identification = strain.identifications.get()
    assert body == {
        "public_id": str(strain.public_id),
        "accession_number": "MYC 1",
        "name_as_received": "Testella exempli T1",
        "taxon": {
            "public_id": str(exempli.public_id),
            "name": "Testella exempli",
            "authority": "Doe 2001",
            "rank": "species",
            "status": "accepted",
        },
        "risk_group": 2,
        "status": "active",
        "restrictions": [
            {"kind": "dual_use", "reference": "1C351.c"},
            {"kind": "gmo", "reference": "MŽP 2026/12"},
        ],
        "created_at": body["created_at"],
        "animal_pathogenicity": "none_known",
        "plant_pathogenicity": "pathogenic",
        "isolation_source": "garden soil",
        "country_of_origin": "CZ",
        "isolation_date": "2019-05",
        "identifications": [
            {
                "public_id": str(identification.public_id),
                "taxon": body["taxon"],
                "identified_on": "2026-01-10",
                "method": "16S rRNA gene sequence",
                "reason": "Identification at accession",
                "is_current": True,
                "created_at": body["identifications"][0]["created_at"],
            }
        ],
        "restriction_history": [
            {
                "public_id": body["restriction_history"][0]["public_id"],
                "kind": "dual_use",
                "reference": "1C351.c",
                "act": "(EU) 2025/2003",
                "gmo_category": None,
                "created_at": body["restriction_history"][0]["created_at"],
                "ended_at": None,
                "end_reason": "",
                "end_proposal": None,
            },
            {
                "public_id": body["restriction_history"][1]["public_id"],
                "kind": "gmo",
                "reference": "MŽP 2026/12",
                "act": "",
                "gmo_category": 2,
                "created_at": body["restriction_history"][1]["created_at"],
                "ended_at": None,
                "end_reason": "",
                "end_proposal": None,
            },
        ],
    }
    assert AuditEvent.objects.count() == events  # reading records nothing


def test_strains_are_not_created_here_any_more(curator: User, lab: Lab, exempli: Taxon) -> None:
    """A strain comes from an accepted deposit (deposits.services.deposit_accept)."""
    assert_problem(post(curator, payload(exempli)), 405, "method_not_allowed")
    assert not Strain.objects.exists()


def field_code(body: dict[str, Any], attr: str) -> str:
    codes: list[str] = [e["code"] for e in body["errors"] if e["attr"] == attr]
    assert codes, body
    return codes[0]


def test_reclassify_risk_group_and_restrictions_through_the_actions(
    curator: User, manager: User, make_strain: MakeStrain, mockia: Taxon
) -> None:
    strain = make_strain(restrictions=[GMO])
    base = f"{strain.public_id}/"
    body = post(
        curator,
        {
            "taxon": str(mockia.public_id),
            "identified_on": "2026-03-01",
            "method": "MALDI-TOF MS",
            "reason": "sequence differs",
        },
        f"{base}reclassify/",
    ).json()
    assert body["taxon"]["name"] == "Mockia vulgaris"
    assert [(i["taxon"]["name"], i["is_current"]) for i in body["identifications"]] == [
        ("Mockia vulgaris", True),
        ("Testella exempli", False),
    ]
    assert (
        post(curator, {"risk_group": 2, "reason": "reassessed"}, f"{base}risk-group/").json()[
            "risk_group"
        ]
        == 2
    )
    body = post(
        curator,
        {"kind": "dual_use", "reference": "1C351.c", "act": "(EU) 2025/2003", "reason": "listed"},
        f"{base}restrictions/",
    ).json()
    assert [r["kind"] for r in body["restrictions"]] == ["dual_use", "gmo"]
    gmo = StrainRestriction.objects.get(strain=strain, kind="gmo")
    end = f"{base}restrictions/{gmo.public_id}/end-proposal/"
    body = post(curator, {"reason": "destroyed"}, end).json()
    assert [r["kind"] for r in body["restrictions"]] == ["dual_use", "gmo"]  # still in force
    proposal = next(r for r in body["restriction_history"] if r["kind"] == "gmo")["end_proposal"]
    assert proposal == {
        "public_id": proposal["public_id"],
        "reason": "destroyed",
        "proposed_at": proposal["proposed_at"],
        "confirm_refusal": "confirm_own_end_proposal",  # the curator proposed it
    }
    body = post(manager, {"proposal": proposal["public_id"]}, f"{end}confirm/").json()
    assert [r["kind"] for r in body["restrictions"]] == ["dual_use"]
    ended = next(r for r in body["restriction_history"] if r["kind"] == "gmo")
    assert (ended["end_reason"], ended["ended_at"] is not None) == ("destroyed", True)
    assert body["restriction_history"][-1]["kind"] == "gmo"  # ended ones last
    events = (
        AuditEvent.objects.filter(strain_id=strain.public_id)
        .order_by("pk")
        .values_list("event_type", flat=True)
    )
    assert list(events) == [
        "strain_created",
        "strain_reclassified",
        "strain_risk_group_changed",
        "strain_restriction_added",
        "strain_restriction_end_proposed",
        "strain_restriction_ended",
    ]


@pytest.mark.parametrize(
    ("path", "body", "code", "attr"),
    [
        (
            "reclassify/",
            {"taxon": "x", "identified_on": "2026-03-01", "method": "m", "reason": "r"},
            "does_not_exist",
            "taxon",
        ),
        (
            "reclassify/",
            {"identified_on": "2026-03-01", "method": "m", "reason": " "},
            "blank",
            "reason",
        ),
        ("risk-group/", {"risk_group": 4, "reason": "r"}, "risk_group_4_refused", "risk_group"),
        ("risk-group/", {"risk_group": 2}, "required", "reason"),
        (
            "restrictions/",
            {"kind": "dual_use", "reference": "1C351.c", "reason": "r"},
            "invalid",
            "act",
        ),
        (
            "restrictions/",
            {
                "kind": "gmo",
                "reference": "MŽP notification 2026/12",
                "gmo_category": 1,
                "reason": "r",
            },
            "unique",
            "reference",
        ),
    ],
)
def test_action_errors_name_their_field(
    *, curator: User, make_strain: MakeStrain, path: str, body: dict[str, Any], code: str, attr: str
) -> None:
    strain = make_strain(restrictions=[GMO])
    events = AuditEvent.objects.count()
    top = code if code in DOMAIN_CODES else "invalid"
    answer = assert_problem(post(curator, body, f"{strain.public_id}/{path}"), 400, top, attr=attr)
    assert field_code(answer, attr) == code
    assert AuditEvent.objects.count() == events


def test_an_added_vrat_restriction_without_the_permit_is_422(
    curator: User, make_strain: MakeStrain
) -> None:
    strain = make_strain()
    body = {"kind": "cz_vrat", "reference": "Příloha 1, bod 2", "reason": "listed"}
    assert_problem(
        post(curator, body, f"{strain.public_id}/restrictions/"),
        422,
        "lab_authorisation_required",
        attr="kind",
    )


def test_proposing_to_end_an_ended_restriction_is_409(
    curator: User, manager: User, make_strain: MakeStrain
) -> None:
    strain = make_strain(restrictions=[GMO])
    gmo = StrainRestriction.objects.get(strain=strain)
    end_restriction(gmo, proposer=curator, confirmer=manager, reason="destroyed")
    response = post(
        curator,
        {"reason": "again"},
        f"{strain.public_id}/restrictions/{gmo.public_id}/end-proposal/",
    )
    assert_problem(response, 409, "restriction_ended")


def test_a_restriction_of_another_strain_is_not_found_through_this_one(
    curator: User, make_strain: MakeStrain
) -> None:
    one, two = make_strain(), make_strain(restrictions=[GMO])
    gmo = StrainRestriction.objects.get(strain=two)
    response = post(
        curator, {"reason": "x"}, f"{one.public_id}/restrictions/{gmo.public_id}/end-proposal/"
    )
    assert_problem(response, 404, "not_found")
    assert not gmo.end_proposals.exists()


# The list: filters, order, pages.


def listed(user: User, **params: Any) -> list[str]:
    response = logged_in(user).get(STRAINS_URL, params)
    assert response.status_code == 200, response.content
    return [row["name_as_received"] for row in response.json()["results"]]


@pytest.fixture
def collection(
    *,
    make_strain: MakeStrain,
    other_lab: Lab,
    outsider: User,
    exempli: Taxon,
    alpha: Taxon,
    fictivibrio: Taxon,
    mockia: Taxon,
) -> None:
    make_strain(name_as_received="sub", taxon=exempli, risk_group=1, restrictions=[DUAL_USE])
    make_strain(name_as_received="spiz", taxon=alpha, risk_group=2)
    make_strain(name_as_received="vib", taxon=fictivibrio, risk_group=1)
    make_strain(name_as_received="mockia", taxon=mockia, risk_group=2, restrictions=[GMO])
    make_strain(lab=other_lab, actor=outsider, name_as_received="other lab sub", taxon=exempli)


@pytest.mark.usefixtures("collection")
def test_the_taxon_filter_takes_descendants_and_synonyms_never_another_lab(
    *,
    viewer: User,
    testella: Taxon,
    exempli: Taxon,
    alpha: Taxon,
    fictivibrio: Taxon,
    mockia: Taxon,
) -> None:
    assert listed(viewer, taxon=testella.public_id) == ["sub", "spiz", "vib"]
    assert listed(viewer, taxon=exempli.public_id) == ["sub", "spiz", "vib"]
    assert listed(viewer, taxon=fictivibrio.public_id) == [
        "sub",
        "spiz",
        "vib",
    ]  # its accepted name
    assert listed(viewer, taxon=alpha.public_id) == ["spiz"]
    assert listed(viewer, taxon=mockia.public_id) == ["mockia"]


@pytest.mark.usefixtures("collection")
def test_the_other_filters_narrow_within_the_lab(viewer: User, make_strain: MakeStrain) -> None:
    assert listed(viewer, risk_group=2) == ["spiz", "mockia"]
    assert listed(viewer, restriction="dual_use") == ["sub"]
    assert listed(viewer, restriction="gmo") == ["mockia"]
    assert listed(viewer, restriction="cz_vrat") == []
    assert listed(viewer, status="active") == ["sub", "spiz", "vib", "mockia"]
    assert listed(viewer, status="deaccessioned") == []
    assert listed(viewer, search="MYC 4") == ["mockia"]
    assert listed(viewer, search=" sp ") == ["spiz"]
    assert listed(viewer, search="mockia") == ["mockia"]  # the current taxon's name
    assert listed(viewer, search="other lab") == []
    assert listed(viewer, risk_group=1, restriction="dual_use") == ["sub"]


@pytest.mark.usefixtures("collection")
def test_an_ended_restriction_no_longer_matches(viewer: User, curator: User, manager: User) -> None:
    gmo = StrainRestriction.objects.get(kind="gmo")
    end_restriction(gmo, proposer=curator, confirmer=manager, reason="destroyed")
    assert listed(viewer, restriction="gmo") == []


@pytest.mark.parametrize(
    ("params", "attr"),
    [
        ({"risk_group": 9}, "risk_group"),
        ({"status": "lost"}, "status"),
        ({"restriction": "toxin"}, "restriction"),
        ({"taxon": "00000000-0000-4000-8000-000000000999"}, "taxon"),
        ({"taxon": "x"}, "taxon"),
    ],
)
def test_an_unknown_filter_value_is_400_never_the_whole_list(
    viewer: User, lab: Lab, params: dict[str, Any], attr: str
) -> None:
    assert_problem(logged_in(viewer).get(STRAINS_URL, params), 400, "invalid", attr=attr)


def test_numbers_sort_as_numbers_and_pages_neither_repeat_nor_skip(
    viewer: User, make_strain: MakeStrain
) -> None:
    for i in range(11):
        make_strain(name_as_received=f"s{i + 1}")
    rows = logged_in(viewer).get(STRAINS_URL, {"limit": 4, "offset": 8}).json()["results"]
    assert [row["accession_number"] for row in rows] == ["MYC 9", "MYC 10", "MYC 11"]
    pages = [
        logged_in(viewer).get(STRAINS_URL, {"limit": 4, "offset": n}).json()["results"]
        for n in (0, 4, 8)
    ]
    assert [row["accession_number"] for page in pages for row in page] == [
        f"MYC {n}" for n in range(1, 12)
    ]


# Exact, flat query counts, with the lab scope in the SQL.


def scoped(queries: list[dict[str, str]]) -> list[str]:
    return [
        q["sql"]
        for q in queries
        if 'FROM "strains_strain"' in q["sql"] and '"strains_strain"."lab_id" IN (' in q["sql"]
    ]


@pytest.mark.parametrize("rows", [1, 20])
@pytest.mark.parametrize("taxon_filter", [False, True])
def test_the_list_query_count_is_exact_and_flat(
    *,
    rows: int,
    taxon_filter: bool,
    viewer: User,
    make_strain: MakeStrain,
    testella: Taxon,
    query_baseline: QueryBaseline,
) -> None:
    for _ in range(rows):
        make_strain(restrictions=[DUAL_USE, GMO])
    client = logged_in(viewer)
    params = {"taxon": str(testella.public_id)} if taxon_filter else {}
    # Session, user, memberships, the lab, (the filter's taxon), count, page with the taxon
    # joined, the active restrictions prefetched.
    with query_baseline("strain_list_by_taxon" if taxon_filter else "strain_list") as captured:
        response = client.get(STRAINS_URL, params)
    assert response.json()["count"] == rows
    assert scoped(captured.captured_queries)


@pytest.mark.parametrize("identifications", [1, 5])
def test_the_detail_query_count_is_exact_and_flat(
    *,
    identifications: int,
    viewer: User,
    curator: User,
    make_strain: MakeStrain,
    mockia: Taxon,
    query_baseline: QueryBaseline,
) -> None:
    strain = make_strain(restrictions=[DUAL_USE, GMO])
    for _ in range(identifications - 1):
        post(
            curator,
            {
                "taxon": str(mockia.public_id),
                "identified_on": "2026-03-01",
                "method": "m",
                "reason": "r",
            },
            f"{strain.public_id}/reclassify/",
        )
    client = logged_in(viewer)
    with query_baseline("strain_detail"):
        response = client.get(f"{STRAINS_URL}{strain.public_id}/")
    assert len(response.json()["identifications"]) == identifications

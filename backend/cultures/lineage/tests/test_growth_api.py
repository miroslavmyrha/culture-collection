"""A subculture and a revival through the API record how they were grown (#79): the strain's
conditions when the body names none, the body's when it does, and a field error for the rest."""

from typing import Any

import pytest

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.core.testing import assert_problem, logged_in
from cultures.growth import services as growth
from cultures.growth.models import GrowthMedium
from cultures.growth.services import Growth
from cultures.labs.access import access_for
from cultures.lineage.models import Passage
from cultures.strains import services as strains
from cultures.strains.models import Strain
from cultures.users.models import User

from .support import PASSAGES_URL, VIALS_URL, MakeBatch, vials_of

pytestmark = pytest.mark.django_db


@pytest.fixture
def broth(curator: User, strain: Strain) -> GrowthMedium:
    with audit_context(channel=Channel.API, actor=curator, request_id="req-m"):
        medium = growth.medium_create(access=access_for(curator), lab=strain.lab, name="Broth")
        strains.strain_set_growth(
            access=access_for(curator),
            strain=strain,
            growth=Growth(medium, 30, 30, "aerobic"),
            reason="From the sheet",
        )
    return medium


def post(user: User, url: str, body: dict[str, Any] | None = None) -> Any:
    return logged_in(user).post(url, body or {}, content_type="application/json")


def test_a_subculture_shows_the_strains_conditions_and_an_override(
    technician: User, curator: User, passage0: Passage, broth: GrowthMedium, strain: Strain
) -> None:
    default = post(technician, PASSAGES_URL, {"source_passage": str(passage0.public_id)}).json()
    assert default["growth"]["medium"]["name"] == "Broth"
    assert (default["growth"]["temperature_low_c"], default["growth"]["atmosphere"]) == (
        30,
        "aerobic",
    )
    with audit_context(channel=Channel.API, actor=curator, request_id="req-o"):
        agar = growth.medium_create(access=access_for(curator), lab=strain.lab, name="Agar")
    other = post(
        technician,
        PASSAGES_URL,
        {
            "source_passage": str(passage0.public_id),
            "growth": {
                "medium": str(agar.public_id),
                "temperature_low_c": 25,
                "temperature_high_c": 28,
                "atmosphere": "anaerobic",
            },
        },
    ).json()
    assert other["growth"]["medium"]["name"] == "Agar"
    assert (other["growth"]["temperature_low_c"], other["growth"]["temperature_high_c"]) == (25, 28)
    assert other["growth"]["atmosphere"] == "anaerobic"
    strain.refresh_from_db()
    assert strain.growth_medium == broth  # the strain keeps its own


def test_passage_zero_has_no_conditions(passage0: Passage, technician: User) -> None:
    row = logged_in(technician).get(f"{PASSAGES_URL}{passage0.public_id}/").json()
    assert row["growth"] == {
        "medium": None,
        "temperature_low_c": None,
        "temperature_high_c": None,
        "atmosphere": "",
    }


def test_a_revival_takes_the_strains_conditions_or_the_bodys(
    technician: User, passage0: Passage, make_batch: MakeBatch, broth: GrowthMedium
) -> None:
    one = Passage.objects.get(
        public_id=post(
            technician, PASSAGES_URL, {"source_passage": str(passage0.public_id)}
        ).json()["public_id"]
    )
    vials = vials_of(make_batch(one, vial_count=2))
    plain = post(technician, f"{VIALS_URL}{vials[0].public_id}/revive/").json()
    assert plain["growth"]["medium"]["name"] == "Broth"
    chosen = post(
        technician,
        f"{VIALS_URL}{vials[1].public_id}/revive/",
        {"growth": {"temperature_low_c": 37, "atmosphere": "microaerophilic"}},
    ).json()
    assert chosen["growth"] == {
        "medium": None,
        "temperature_low_c": 37,
        "temperature_high_c": 37,
        "atmosphere": "microaerophilic",
    }


def test_a_bad_override_is_a_field_error_and_makes_no_passage(
    technician: User, passage0: Passage
) -> None:
    before = Passage.objects.count()
    response = post(
        technician,
        PASSAGES_URL,
        {"source_passage": str(passage0.public_id), "growth": {"temperature_low_c": 300}},
    )
    assert_problem(response, 400, "invalid", "temperature_low_c")
    assert Passage.objects.count() == before

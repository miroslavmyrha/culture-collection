"""The scale check (#71): a count that grows with the data, a slow screen or an error fails."""

from __future__ import annotations

import pytest

from cultures.strains.tests.test_seed_dev import env, seed  # noqa: F401 (env is a fixture)
from cultures.strains.tests.test_seed_scale import scale
from tools.measure_scale import main, problems

SMALL = {"strain list": {"ms": 20.0, "queries": 13, "status": 200}}


def test_the_same_counts_under_budget_pass() -> None:
    large = {"strain list": {"ms": 40.0, "queries": 13, "status": 200}}
    assert problems(large, SMALL, 1500) == []


def test_a_count_that_grew_with_the_data_fails() -> None:
    large = {"strain list": {"ms": 40.0, "queries": 14, "status": 200}}
    assert problems(large, SMALL, None) == ["strain list: 14 queries, 13 on fewer rows"]


def test_a_screen_over_budget_fails() -> None:
    large = {"strain list": {"ms": 1600.0, "queries": 13, "status": 200}}
    assert problems(large, SMALL, 1500) == ["strain list: 1600.0 ms over 1500"]


def test_an_error_fails_without_a_comparison() -> None:
    assert problems({"strain list": {"ms": 5.0, "queries": 3, "status": 500}}, None, None) == [
        "strain list: status 500"
    ]


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_it_measures_every_screen_of_a_seeded_lab(capsys: pytest.CaptureFixture[str]) -> None:
    seed()
    scale("--strains", "2", "--vials", "2")
    measured = main("BAC", "bac-manager", host="testserver")
    assert len(measured) == 14
    assert {r["status"] for r in measured.values()} == {200}
    assert all(r["queries"] > 0 for r in measured.values())
    assert "| strain list |" in capsys.readouterr().out

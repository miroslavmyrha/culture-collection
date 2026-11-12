"""The command line that shows what a seed's entry codes come to (#211)."""

import json

import pytest

from tools import seed_classification


def test_show_gives_the_taxon_group_pointer_and_restrictions() -> None:
    answer = seed_classification.run(["show", "1.56", "annex-2 I.II 3"])
    assert (answer["taxon"], answer["risk_group"], answer["risk_group_entry"]) == (
        "Clostridium tetani",
        2,
        "1.56",
    )
    assert [r["kind"] for r in answer["restrictions"]] == ["cz_rat"]


def test_find_lists_the_entries_a_name_matches() -> None:
    answer = seed_classification.run(["find", "Escherichia coli"])
    assert "1.73" in {e["code"] for e in answer["entries"]}


def test_the_command_line_prints_json_and_exits_1_on_an_unknown_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert seed_classification.main(["show", "99.99"]) == 1
    assert "no entry" in capsys.readouterr().err
    assert seed_classification.main(["standard", "bacillus-subtilis-168"]) == 0
    assert json.loads(capsys.readouterr().out)["risk_group"] == 1

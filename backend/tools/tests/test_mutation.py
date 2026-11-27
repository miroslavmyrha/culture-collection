"""The nightly mutation run's own logic (#239): what counts as a survivor, the baseline, the
config per area. mutmut itself runs only on CI."""

import tomllib
from configparser import ConfigParser
from pathlib import Path

import pytest

from tools import mutation

BACKEND = Path(__file__).resolve().parents[2]

RESULTS = """\
    cultures.audit.events.x_record_event__mutmut_3: survived
    cultures.audit.events.x_record_event__mutmut_4: killed
    cultures.audit.events.x_record_event__mutmut_5: no tests
    cultures.audit.context.x_audited_atomic__mutmut_1: timeout
    cultures.audit.context.x_audited_atomic__mutmut_2: suspicious
Some other line: not a status
"""


def test_survived_no_tests_and_suspicious_are_not_killed() -> None:
    assert mutation.not_killed(RESULTS) == {
        "cultures.audit.events.x_record_event__mutmut_3": "survived",
        "cultures.audit.events.x_record_event__mutmut_5": "no tests",
        "cultures.audit.context.x_audited_atomic__mutmut_2": "suspicious",
    }


def test_a_new_survivor_fails_and_a_killed_baseline_entry_is_named() -> None:
    found = {"a__mutmut_1": "survived", "b__mutmut_2": "survived"}
    baseline = {"a__mutmut_1": "equivalent: logs only", "c__mutmut_9": "killed by #239"}
    assert mutation.compare(found, baseline) == (["b__mutmut_2"], ["c__mutmut_9"])


def test_the_run_exits_1_only_for_a_new_survivor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outputs = iter(["", RESULTS])

    class Done:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout
            self.returncode = 0

    monkeypatch.setattr(mutation, "BACKEND", tmp_path)
    monkeypatch.setattr("tools.mutation.subprocess.run", lambda *a, **k: Done(next(outputs, "")))
    baseline = tmp_path / "baseline.toml"
    known = [
        "cultures.audit.events.x_record_event__mutmut_3",
        "cultures.audit.events.x_record_event__mutmut_5",
        "cultures.audit.context.x_audited_atomic__mutmut_2",
    ]
    baseline.write_text("[audit]\n" + "".join(f'"{name}" = "known"\n' for name in known))
    monkeypatch.setattr(mutation, "BASELINE", baseline)
    summary = tmp_path / "summary.md"
    assert mutation.run("audit", 1, summary) == 0
    assert "Not killed: 3 (0 new, 3 in the baseline)." in summary.read_text()

    outputs = iter(["", RESULTS])
    baseline.write_text('[audit]\n"cultures.audit.events.x_record_event__mutmut_3" = "known"\n')
    assert mutation.run("audit", 1, summary) == 1
    assert "`cultures.audit.events.x_record_event__mutmut_5`: no tests" in summary.read_text()


def test_each_area_writes_a_config_mutmut_reads() -> None:
    for name, area in mutation.AREAS.items():
        parser = ConfigParser()
        parser.read_string(mutation.setup_cfg(area))
        only = [line for line in parser.get("mutmut", "only_mutate").split("\n") if line]
        tests = [
            line
            for line in parser.get("mutmut", "pytest_add_cli_args_test_selection").split("\n")
            if line
        ]
        assert only == list(area.sources), name
        assert tests == list(area.tests), name
        assert "not slow" in parser.get("mutmut", "pytest_add_cli_args")


def test_every_file_an_area_names_exists() -> None:
    for name, area in mutation.AREAS.items():
        for path in (*area.sources, *area.tests):
            assert (BACKEND / path).is_file(), f"{name}: {path}"


def test_the_baseline_names_only_known_areas() -> None:
    if mutation.BASELINE.exists():
        assert set(tomllib.loads(mutation.BASELINE.read_text())) <= set(mutation.AREAS)


def test_areas_prints_the_matrix(capsys: pytest.CaptureFixture[str]) -> None:
    assert mutation.main(["areas"]) == 0
    assert capsys.readouterr().out.split() == sorted(mutation.AREAS)


def test_a_run_that_checked_no_mutant_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 2026-11-25: a test failed before any mutant ran, mutmut left nothing, the night was green.
    class Done:
        def __init__(self, stdout: str, code: int) -> None:
            self.stdout, self.returncode = stdout, code

    monkeypatch.setattr(mutation, "BACKEND", tmp_path)
    summary = tmp_path / "summary.md"
    for code, results in ((0, ""), (1, RESULTS)):
        answers = iter([Done("", code), Done(results, 0)])
        monkeypatch.setattr(
            "tools.mutation.subprocess.run", lambda *a, _answers=answers, **k: next(_answers)
        )
        assert mutation.run("audit", 1, summary) == 1
    assert summary.read_text().count("mutmut did not run its mutants") == 2


def test_a_module_reading_test_is_deselected_in_its_area() -> None:
    parser = ConfigParser()
    parser.read_string(mutation.setup_cfg(mutation.AREAS["strains-risk_group"]))
    args = [line for line in parser.get("mutmut", "pytest_add_cli_args").split("\n") if line]
    assert args[-2:] == [
        "--deselect",
        "cultures/strains/tests/test_services.py"
        "::test_every_public_strain_service_has_a_strain_id_scenario",
    ]


def test_every_group_file_is_its_own_area_but_the_small_ones() -> None:
    sources = sorted(path for area in mutation.AREAS.values() for path in area.sources)
    assert sources == sorted(path for group in mutation.GROUPS.values() for path in group.sources)
    assert mutation.AREAS["audit"] == mutation.GROUPS["audit"]
    assert mutation.AREAS["users-factors"].sources == ("cultures/users/factors.py",)
    assert mutation.AREAS["users-factors"].tests == mutation.GROUPS["users"].tests


def test_a_source_with_extra_tests_runs_them_and_its_siblings_do_not() -> None:
    decisions = mutation.AREAS["distribution-decisions"]
    group = mutation.GROUPS["distribution"]
    extra = mutation.EXTRA["cultures/distribution/services/decisions.py"]
    assert decisions.tests == group.tests + extra.tests
    assert decisions.deselect == group.deselect + extra.deselect
    assert mutation.AREAS["distribution-policy"].tests == group.tests
    assert set(mutation.EXTRA) <= {p for g in mutation.GROUPS.values() for p in g.sources}

"""The code risk score: known complexity and coverage give a known score, and gaps are named."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.crap import (
    Func,
    count_over,
    crap,
    main,
    python_functions,
    quartiles,
    typescript_functions,
)


def test_formula_known_values() -> None:
    assert crap(1, 1.0) == 1
    assert crap(10, 1.0) == 10  # fully covered: the score is the complexity
    assert crap(10, 0.0) == 110  # untested: complexity squared plus complexity
    assert crap(10, 0.5) == pytest.approx(10 * 10 * 0.125 + 10)
    assert crap(20, 0.8) == pytest.approx(400 * 0.008 + 20)


def test_formula_rejects_coverage_outside_zero_to_one() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        crap(3, 1.5)


def _cov(executed: list[int], missing: list[int]) -> dict[str, Any]:
    return {"executed_lines": executed, "missing_lines": missing}


def _block(name: str, lineno: int, endline: int, complexity: int, **extra: Any) -> dict[str, Any]:
    return {"type": "function", "name": name, "lineno": lineno, "endline": endline,
            "complexity": complexity, **extra}  # fmt: skip


def test_python_function_with_known_complexity_and_coverage() -> None:
    # def on line 10, four statements in the body, three of them ran
    coverage = {"files": {"/app/a/views.py": _cov([10, 11, 12, 13], [14])}}
    radon = {"/app/a/views.py": [_block("view", 10, 14, 5)]}
    funcs, missing, skipped = python_functions(coverage, radon)
    assert (missing, skipped) == ([], [])
    (f,) = funcs
    assert (f.file, f.line, f.name, f.complexity) == ("a/views.py", 10, "view", 5)
    assert f.coverage == 0.75  # the def line (10) is not counted
    assert f.score == pytest.approx(25 * 0.25**3 + 5)


def test_python_function_without_statements_is_skipped() -> None:
    coverage = {"files": {"/app/a/m.py": _cov([1, 5], [])}}
    radon = {"/app/a/m.py": [_block("empty", 1, 3, 1)]}
    funcs, missing, skipped = python_functions(coverage, radon)
    assert funcs == []
    assert skipped == ["a/m.py:1 empty"]
    assert missing == []


def test_python_file_without_coverage_data_is_reported_not_scored() -> None:
    radon = {"/app/a/never_imported.py": [_block("f", 1, 4, 3)]}
    funcs, missing, _ = python_functions({"files": {}}, radon)
    assert funcs == []
    assert missing == ["a/never_imported.py"]


def test_python_methods_and_closures_are_their_own_functions() -> None:
    coverage = {"files": {"/app/a/m.py": _cov([2, 3, 4, 5, 6], [7])}}
    method = _block("get", 3, 7, 2, closures=[_block("inner", 5, 6, 1)])
    method["type"] = "method"
    radon = {"/app/a/m.py": [{"type": "class", "name": "V", "lineno": 2, "endline": 7,
                              "complexity": 3, "methods": [method]}]}  # fmt: skip
    funcs, _, _ = python_functions(coverage, radon)
    assert sorted(f.name for f in funcs) == ["V.get", "V.get.inner"]


@pytest.mark.parametrize(
    "path",
    [
        "/app/cultures/strains/migrations/0001_initial.py",
        "/app/cultures/strains/tests/test_views.py",
        "/app/cultures/core/testing/factories.py",
        "/app/conftest.py",
    ],
)
def test_python_excluded_paths_are_not_measured(path: str) -> None:
    coverage = {"files": {path: _cov([2], [3])}}
    funcs, missing, skipped = python_functions(coverage, {path: [_block("f", 1, 3, 9)]})
    assert (funcs, missing, skipped) == ([], [], [])


def _ts_coverage(hits: list[int]) -> dict[str, Any]:
    """One function on lines 3 to 9, one statement per hit on lines 4, 5, ..."""

    def pos(line: int, col: int) -> dict[str, int]:
        return {"line": line, "column": col}

    return {
        "/w/src/a.ts": {
            "fnMap": {"0": {"name": "f", "loc": {"start": pos(3, 0), "end": pos(9, 1)}}},
            "statementMap": {
                str(i): {"start": pos(4 + i, 2), "end": pos(4 + i, 10)} for i in range(len(hits))
            },
            "s": {str(i): h for i, h in enumerate(hits)},
        }
    }


def _diag(file: str, line: int, column: int, complexity: int) -> dict[str, Any]:
    return {
        "message": f"function `f` has a complexity of {complexity}. Maximum allowed is 1.",
        "filename": file,
        "labels": [{"span": {"line": line, "column": column}}],
    }


def test_typescript_function_with_known_complexity_and_coverage() -> None:
    cov = _ts_coverage([1, 1, 0, 0])
    funcs, missing, skipped, unmatched = typescript_functions(
        cov, [_diag("src/a.ts", 3, 8, 4)], "/w"
    )
    assert (missing, skipped, unmatched) == ([], [], [])
    (f,) = funcs
    assert (f.file, f.line, f.name, f.complexity, f.coverage) == ("src/a.ts", 3, "f", 4, 0.5)
    assert f.score == pytest.approx(16 * 0.125 + 4)


def test_typescript_function_oxlint_does_not_mention_has_complexity_one() -> None:
    funcs, _, _, _ = typescript_functions(_ts_coverage([0]), [], "/w")
    assert funcs[0].complexity == 1
    assert funcs[0].score == 2


def test_typescript_function_without_statements_is_skipped() -> None:
    funcs, _, skipped, _ = typescript_functions(_ts_coverage([]), [], "/w")
    assert funcs == []
    assert skipped == ["src/a.ts:3 f"]


def test_typescript_complexity_that_matches_no_function_is_reported() -> None:
    _, _, _, unmatched = typescript_functions(
        _ts_coverage([1]), [_diag("src/a.ts", 40, 0, 6)], "/w"
    )
    assert unmatched == ["src/a.ts:40 complexity 6"]


def test_typescript_file_with_complexity_but_no_coverage_data_is_reported() -> None:
    funcs, missing, _, _ = typescript_functions({}, [_diag("src/b.ts", 1, 0, 3)], "/w")
    assert (funcs, missing) == ([], ["src/b.ts"])


def test_typescript_test_files_are_not_measured() -> None:
    cov = {"/w/src/a.test.ts": _ts_coverage([0])["/w/src/a.ts"]}
    funcs, _, _, _ = typescript_functions(cov, [], "/w")
    assert funcs == []


def test_quartiles_and_count_over() -> None:
    assert quartiles([1, 2, 3, 4, 5]) == (1, 2, 3, 4, 5)
    assert quartiles([]) == (0, 0, 0, 0, 0)
    funcs = [Func("python", "a", 1, str(s), 1, 1.0, s) for s in (5, 10, 11, 40)]
    assert count_over(funcs, 10) == 2  # a score equal to the limit is not over it


def test_command_line_prints_the_distribution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cov, radon = tmp_path / "c.json", tmp_path / "r.json"
    cov.write_text(json.dumps({"files": {"/app/a.py": _cov([1, 2], [3])}}))
    radon.write_text(json.dumps({"/app/a.py": [_block("f", 1, 3, 4)]}))
    assert main(["--py-coverage", str(cov), "--py-radon", str(radon), "--limits", "5,50"]) == 0
    out = capsys.readouterr().out
    assert "python: 1 functions measured" in out
    assert "> 5: 1, > 50: 0" in out
    assert "| a.py | 1 | f | 4 | 50% |" in out


def test_command_line_without_inputs_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "nothing to measure" in capsys.readouterr().err


def test_python_method_listed_at_top_level_and_under_its_class_counts_once() -> None:
    coverage = {"files": {"/app/a/m.py": _cov([2, 3, 4], [5])}}
    method = _block("get", 3, 5, 2)
    method["type"] = "method"
    top = {**method, "classname": "V"}
    cls = {"type": "class", "name": "V", "lineno": 2, "endline": 5, "complexity": 2,
           "methods": [method]}  # fmt: skip
    funcs, _, _ = python_functions(coverage, {"/app/a/m.py": [top, cls]})
    assert [f.name for f in funcs] == ["V.get"]

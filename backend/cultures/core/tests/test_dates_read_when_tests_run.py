"""No test reads today's date while the tests are collected (#60).

A date in a parametrize list or at module level is taken when pytest collects the file. A run
that crosses midnight then checks yesterday's "tomorrow" against today: CI collected at 23:55 on
2026-10-25 and a test that wanted a future day got today. Build such values in the test body,
or pass a callable that builds them.
"""

import ast
from pathlib import Path

from django.conf import settings

# Calls that read the day. timezone.now() alone is left out: a timestamp that only has to exist
# (a status changed at, a unit retired at) does not care which day it is.
DAY_READERS = {"permit_today", "today", "localdate"}


def collection_time_reads(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    places: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            places += node.decorator_list
        elif isinstance(node, ast.ClassDef):
            places += node.decorator_list
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    places += item.decorator_list
                else:
                    places.append(item)
        else:
            places.append(node)
    found = []
    for place in places:
        for sub in ast.walk(place):
            if isinstance(sub, ast.Lambda):
                continue
            if isinstance(sub, ast.Call):
                func = sub.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name in DAY_READERS and not inside_lambda(place, sub):
                    found.append(f"{label(path)}:{sub.lineno}: {ast.unparse(sub)}")
    return found


def label(path: Path) -> str:
    base = Path(settings.BASE_DIR)
    return str(path.relative_to(base)) if path.is_relative_to(base) else path.name


def inside_lambda(root: ast.AST, call: ast.Call) -> bool:
    """A call inside a lambda runs when the test calls it, not at collection."""
    return any(
        isinstance(node, ast.Lambda) and any(child is call for child in ast.walk(node))
        for node in ast.walk(root)
    )


def test_no_test_reads_the_day_while_it_is_collected() -> None:
    tests = sorted(Path(settings.BASE_DIR, "cultures").rglob("test*.py"))
    assert tests, "no test files found"
    found = [line for path in tests for line in collection_time_reads(path)]
    assert found == [], "a day read at collection goes stale past midnight:\n" + "\n".join(found)


def test_the_check_sees_a_day_in_a_parametrize_list(tmp_path: Path) -> None:
    probe = tmp_path / "test_probe_day.py"
    probe.write_text(
        "import pytest\n"
        "from datetime import date\n"
        "@pytest.mark.parametrize('day', [date.today()])\n"
        "def test_x(day): pass\n"
        "LATER = [lambda: date.today()]\n",
        encoding="utf-8",
    )
    assert collection_time_reads(probe) == ["test_probe_day.py:3: date.today()"]

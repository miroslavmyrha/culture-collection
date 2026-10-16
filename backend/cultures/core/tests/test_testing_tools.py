"""The shared test tools (cultures.core.testing) refuse what they claim to refuse.

A broken tool passes every test that relies on it, so each one runs here on a
correct target and on broken ones.
"""

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from model_bakery import baker

from cultures.core import testing
from cultures.core.errors import problem
from cultures.core.testing import assert_problem, logged_in, run_before
from cultures.core.testing.queries import UPDATE_ENV, check_query_baseline
from cultures.users.models import User

BACKEND = Path(settings.BASE_DIR)


class TestAssertProblem:
    def response(self, **overrides: Any) -> JsonResponse:
        body = {**problem(404, "not_found", "Not found."), **overrides}
        return JsonResponse(body, status=404, content_type="application/problem+json")

    def test_accepts_the_right_problem(self) -> None:
        assert_problem(self.response(), 404, "not_found")

    @pytest.mark.parametrize(
        ("overrides", "status", "code", "attr"),
        [
            ({}, 400, "not_found", None),  # wrong status
            ({}, 404, "conflict", None),  # wrong code
            ({"title": "Error"}, 404, "not_found", None),
            ({"type": "https://example.com/x"}, 404, "not_found", None),
            ({"extra": 1}, 404, "not_found", None),
            ({}, 404, "not_found", "barcode"),  # no field error for attr
        ],
    )
    def test_refuses_a_wrong_problem(
        self, overrides: dict[str, Any], status: int, code: str, attr: str | None
    ) -> None:
        with pytest.raises(AssertionError):
            assert_problem(self.response(**overrides), status, code, attr)

    def test_refuses_plain_json(self) -> None:
        plain = JsonResponse(problem(404, "not_found", "Not found."), status=404)
        with pytest.raises(AssertionError):
            assert_problem(plain, 404, "not_found")


@pytest.mark.django_db
def test_logged_in_gives_the_users_session() -> None:
    user = baker.make(User)
    assert logged_in(user).session["_auth_user_id"] == str(user.pk)
    assert "_auth_user_id" not in logged_in(None).session


def test_run_before_runs_the_competitor_once_before_the_first_call() -> None:
    calls: list[str] = []
    target = SimpleNamespace(work=lambda: calls.append("work"))
    original = target.work
    with run_before(target, "work", lambda: calls.append("competitor")):
        target.work()
        target.work()
    assert calls == ["competitor", "work", "work"]
    assert target.work is original  # restored after the block


def run_counted(counts: Path, key: str, queries: int) -> None:
    with check_query_baseline(counts, key), connection.cursor() as cursor:
        for _ in range(queries):
            cursor.execute("SELECT 1")


@pytest.mark.django_db
class TestQueryBaseline:
    @pytest.fixture
    def counts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.delenv(UPDATE_ENV, raising=False)
        counts = tmp_path / "query_counts.json"
        counts.write_text(json.dumps({"one": 1}))
        return counts

    def test_passes_on_the_exact_count(self, counts: Path) -> None:
        run_counted(counts, "one", 1)

    @pytest.mark.parametrize("queries", [0, 2])
    def test_fails_on_fewer_and_on_more_queries(self, counts: Path, queries: int) -> None:
        with pytest.raises(pytest.fail.Exception, match=f"{queries} queries, baseline 1"):
            run_counted(counts, "one", queries)

    def test_fails_without_a_baseline_and_says_how_to_record_it(self, counts: Path) -> None:
        with pytest.raises(pytest.fail.Exception, match=f"no baseline for 'two'.*{UPDATE_ENV}=1"):
            run_counted(counts, "two", 1)

    def test_fails_when_one_key_counts_differently_in_two_tests(self, counts: Path) -> None:
        run_counted(counts, "one", 1)
        with pytest.raises(pytest.fail.Exception, match="grows with the data"):
            run_counted(counts, "one", 2)

    def test_records_the_count_when_asked(
        self, counts: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(UPDATE_ENV, "1")
        run_counted(counts, "new", 3)
        assert json.loads(counts.read_text()) == {"new": 3, "one": 1}


def test_pytest_refuses_any_other_settings_module() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--ds=config.settings.local",
            "--collect-only",
            "-p",
            "no:cacheprovider",
            "cultures/core/tests/test_checks.py",
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout + result.stderr
    assert "tests run with config.settings.local, not config.settings.test" in result.stderr


# Every shared test tool has a self-test: the tools exported by cultures.core.testing
# and the public functions of the root conftest (its guard and its fixtures).
SELF_TESTS = {
    "COVERED": "cultures.core.tests.test_viewset_contract:test_a_contract_class_covers_its_viewset",
    "PROBLEM_KEYS": "cultures.core.tests.test_testing_tools:TestAssertProblem",
    "assert_problem": "cultures.core.tests.test_testing_tools:TestAssertProblem",
    "logged_in": "cultures.core.tests.test_testing_tools:test_logged_in_gives_the_users_session",
    "run_before": (
        "cultures.core.tests.test_testing_tools:"
        "test_run_before_runs_the_competitor_once_before_the_first_call"
    ),
    "QueryBaseline": "cultures.core.tests.test_testing_tools:TestQueryBaseline",
    "query_baseline": "cultures.core.tests.test_testing_tools:TestQueryBaseline",
    "ViewsetContract": (
        "cultures.core.tests.test_viewset_contract:test_contract_catches_a_list_without_scope"
    ),
    "Write": (
        "cultures.core.tests.test_viewset_contract:"
        "test_contract_catches_a_refused_write_that_changed_the_row"
    ),
    "pytest_configure": (
        "cultures.core.tests.test_testing_tools:test_pytest_refuses_any_other_settings_module"
    ),
}


def shared_test_tools() -> set[str]:
    conftest = sys.modules["conftest"]  # the root conftest.py, loaded by pytest
    assert Path(conftest.__file__ or "") == BACKEND / "conftest.py"
    public = {name for name in vars(conftest) if not name.startswith("_")}
    own = {name for name in public if getattr(vars(conftest)[name], "__module__", "") == "conftest"}
    return set(testing.__all__) | own


def test_every_shared_test_tool_has_a_self_test() -> None:
    assert set(SELF_TESTS) == shared_test_tools()
    for reference in SELF_TESTS.values():
        module, name = reference.split(":")
        assert hasattr(importlib.import_module(module), name), reference

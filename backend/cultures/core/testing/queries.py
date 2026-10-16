"""Exact query counts from a reviewed baseline file.

`django_assert_max_num_queries(n)` lets a new query slip in under the ceiling and
never records an improvement. An exact count in a reviewed file catches the first
and records the second. Each app keeps its own tests/query_counts.json, next to
the tests that use it; the key names the measured request.

Record or rewrite the counts of one app with a serial run:
    UPDATE_QUERY_COUNTS=1 pytest cultures/<app>/tests
then review the diff of query_counts.json like code.
"""

import json
import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

UPDATE_ENV = "UPDATE_QUERY_COUNTS"
QueryBaseline = Callable[[str], AbstractContextManager[CaptureQueriesContext]]

# Counts measured in this run: a key measured twice (parametrized sizes) must agree.
_measured: dict[tuple[Path, str], int] = {}


def updating() -> bool:
    return os.environ.get(UPDATE_ENV) == "1"


@contextmanager
def check_query_baseline(counts_file: Path, key: str) -> Iterator[CaptureQueriesContext]:
    """Count the queries of the block and compare them with counts_file[key]."""
    if updating() and os.environ.get("PYTEST_XDIST_WORKER"):
        pytest.fail(f"{UPDATE_ENV}=1 needs a serial run: add -p no:xdist")
    with CaptureQueriesContext(connection) as captured:
        yield captured
    actual = len(captured.captured_queries)
    sql = "\n".join(f"  {q['sql']}" for q in captured.captured_queries)
    if _measured.setdefault((counts_file, key), actual) != actual:
        pytest.fail(
            f"{key}: {actual} queries here, {_measured[counts_file, key]} in another test "
            f"with the same key, so the count grows with the data:\n{sql}"
        )
    counts: dict[str, int] = json.loads(counts_file.read_text()) if counts_file.exists() else {}
    if updating():
        counts[key] = actual
        counts_file.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n")
        return
    record = f"record it with {UPDATE_ENV}=1 pytest {counts_file.parent} and review the diff"
    if key not in counts:
        pytest.fail(f"no baseline for {key!r} in {counts_file}: {record}")
    if actual != counts[key]:
        pytest.fail(
            f"{key}: {actual} queries, baseline {counts[key]}. Explain the change "
            f"in the PR and update the baseline ({record}):\n{sql}"
        )


def baseline_for(test_file: Path) -> QueryBaseline:
    """The checker for one test file: its baseline is query_counts.json next to it."""
    counts_file = test_file.with_name("query_counts.json")
    return lambda key: check_query_baseline(counts_file, key)

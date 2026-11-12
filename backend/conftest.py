"""Fixtures and guards for every app's tests. Shared test tools live in cultures.core.testing."""

from collections.abc import Iterator

import pytest
from django.conf import settings
from django.core.cache import cache

# Before the import below: asserts in the shared test tools then report their values
# the way asserts in tests do.
pytest.register_assert_rewrite("cultures.core.testing")

from cultures.biosafety import lists  # noqa: E402
from cultures.biosafety.models import RegulatoryList  # noqa: E402
from cultures.core.testing.queries import QueryBaseline, baseline_for  # noqa: E402

TEST_SETTINGS = "config.settings.test"
# The fixtures that give a test the database. `_django_db_helper` is the one pytest-django
# 4.14 puts behind the `django_db` marker and behind `db` and `transactional_db` alike, so it is
# asked for first; the public names stay for a version that drops it.
DATABASE_FIXTURES = ("_django_db_helper", "transactional_db", "django_db_reset_sequences", "db")


def pytest_configure(config: pytest.Config) -> None:
    """Refuse to run under any other settings module.

    Local settings use the database cache, which adds queries to every request
    (exact query counts fail) and keeps throttle counters between tests.
    pyproject.toml passes --ds, so `docker compose run backend pytest` gets the
    test settings even though compose sets DJANGO_SETTINGS_MODULE to local.
    """
    if settings.SETTINGS_MODULE != TEST_SETTINGS:
        raise pytest.UsageError(
            f"tests run with {settings.SETTINGS_MODULE}, not {TEST_SETTINGS}: "
            "drop the --ds option that changed it"
        )


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """Throttle and login-limit counters live in the cache: no test sees another's."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _official_lists(request: pytest.FixtureRequest) -> None:
    """Every test that touches the database finds the official lists (#169).

    Migration `biosafety/0006_official_lists` loads them, so they come with the schema. A test
    that works in a real transaction (`django_db(transaction=True)`) empties every table when it
    ends, which takes them with it, so this puts them back for the next test. One EXISTS query
    for a test that uses the database, none for a test that does not, and it runs before
    anything the test measures.
    """
    wanted = [name for name in DATABASE_FIXTURES if name in request.fixturenames]
    if not wanted:
        return
    request.getfixturevalue(wanted[0])  # the database before the rows
    if not RegulatoryList.objects.exists():
        lists.load(record=False)


@pytest.fixture
def query_baseline(request: pytest.FixtureRequest) -> QueryBaseline:
    """query_baseline("key") counts the queries of a block against tests/query_counts.json.

    See cultures.core.testing.queries for how to record and review the counts.
    """
    return baseline_for(request.path)

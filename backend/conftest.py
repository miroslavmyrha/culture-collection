"""Fixtures and guards for every app's tests. Shared test tools live in cultures.core.testing."""

from collections.abc import Iterator

import pytest
from django.conf import settings
from django.core.cache import cache

# Before the import below: asserts in the shared test tools then report their values
# the way asserts in tests do.
pytest.register_assert_rewrite("cultures.core.testing")

from cultures.core.testing.queries import QueryBaseline, baseline_for  # noqa: E402

TEST_SETTINGS = "config.settings.test"


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


@pytest.fixture
def query_baseline(request: pytest.FixtureRequest) -> QueryBaseline:
    """query_baseline("key") counts the queries of a block against tests/query_counts.json.

    See cultures.core.testing.queries for how to record and review the counts.
    """
    return baseline_for(request.path)

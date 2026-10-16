"""Liveness and readiness probes, served by the first middleware.

They answer before host validation (CommonMiddleware would reject a probe that
uses the pod IP as Host), before the SSL redirect and without a session.
/healthz: the process answers. /readyz: database, cache and migrations are ready;
503 lists the failing checks by name. Neither reveals versions or error text.
"""

import json
import logging
from collections.abc import Callable

from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

LIVENESS_PATH = "/healthz"
READINESS_PATH = "/readyz"
_CACHE_PROBE_KEY = "readyz-probe"


def check_database() -> bool:
    with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
        cursor.execute("SELECT 1")
        return bool(cursor.fetchone() == (1,))


def check_cache() -> bool:
    cache.set(_CACHE_PROBE_KEY, "ok", timeout=10)
    return bool(cache.get(_CACHE_PROBE_KEY) == "ok")


_migrations_applied = False


def check_migrations() -> bool:
    """No unapplied migrations. Once true it stays true for the process."""
    global _migrations_applied  # noqa: PLW0603 (process-wide memo, reset by a new deploy)
    if not _migrations_applied:
        connection = connections[DEFAULT_DB_ALIAS]
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        _migrations_applied = not executor.migration_plan(targets)
    return _migrations_applied


READINESS_CHECKS: dict[str, Callable[[], bool]] = {
    "database": check_database,
    "cache": check_cache,
    "migrations": check_migrations,
}


def readiness() -> list[str]:
    """Names of the checks that fail."""
    failed = []
    for name, check in READINESS_CHECKS.items():
        try:
            ok = check()
        except Exception:
            logger.warning("readiness check %s failed", name, exc_info=True)
            ok = False
        if not ok:
            failed.append(name)
    return failed


def _json(status: int, body: dict[str, object]) -> HttpResponse:
    response = HttpResponse(json.dumps(body), status=status, content_type="application/json")
    response["Cache-Control"] = "no-store"
    return response


class HealthCheckMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method in {"GET", "HEAD"}:
            if request.path == LIVENESS_PATH:
                return _json(200, {"status": "ok"})
            if request.path == READINESS_PATH:
                failed = readiness()
                if failed:
                    return _json(503, {"status": "unavailable", "failed": failed})
                return _json(200, {"status": "ok"})
        return self.get_response(request)

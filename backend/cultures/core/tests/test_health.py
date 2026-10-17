from collections.abc import Callable

import pytest
from django.conf import settings
from django.core.cache.backends.dummy import DummyCache
from django.db import connection, transaction
from django.db.utils import OperationalError
from django.test import Client

from cultures.audit.roles import Roles, setup
from cultures.core import health

pytestmark = pytest.mark.django_db


def test_liveness_answers_any_host(client: Client) -> None:
    # A probe on the pod IP: CommonMiddleware would reject this Host with 400.
    response = client.get("/healthz", HTTP_HOST="10.0.0.5")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response["Cache-Control"] == "no-store"


def test_unknown_host_is_still_rejected_elsewhere(client: Client) -> None:
    assert client.get("/api/v1/auth/me/", HTTP_HOST="10.0.0.5").status_code == 400


def test_readiness_ok_when_database_cache_and_migrations_are_ready(client: Client) -> None:
    response = client.get("/readyz", HTTP_HOST="10.0.0.5")
    assert response.status_code == 200, response.content
    assert response.json() == {"status": "ok"}


def test_readiness_names_the_failing_checks(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def database_down() -> bool:
        raise OperationalError("connection refused")

    monkeypatch.setitem(health.READINESS_CHECKS, "database", database_down)
    monkeypatch.setitem(health.READINESS_CHECKS, "cache", lambda: False)
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "failed": ["database", "cache"]}
    assert b"connection refused" not in response.content  # no internals in the body


# Each readiness check is proven by breaking its dependency, never by replacing
# the check: a check that always answers True must fail its test.


def missing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "DEFAULT_DB_ALIAS", "missing")  # ConnectionDoesNotExist


def cache_that_keeps_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "cache", DummyCache("dummy", {}))  # set() stores nothing


def unapplied_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    class Executor:
        def __init__(self, connection: object) -> None:
            self.loader = type("Loader", (), {"graph": type("Graph", (), {"leaf_nodes": list})()})()

        def migration_plan(self, targets: object) -> list[str]:
            return ["users.0099_pending"]

    monkeypatch.setattr(health, "_migrations_applied", False)  # the process-wide memo
    monkeypatch.setattr(health, "MigrationExecutor", Executor)


def connected_as_the_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests connect as the owner of every table, which is what production must not do.
    monkeypatch.setattr(settings, "DB_RUNTIME_ROLE_REQUIRED", True)


BREAKERS: dict[str, Callable[[pytest.MonkeyPatch], None]] = {
    "database": missing_database,
    "cache": cache_that_keeps_nothing,
    "migrations": unapplied_migration,
    "runtime_role": connected_as_the_owner,
}


def test_every_readiness_check_has_a_breaker() -> None:
    assert set(BREAKERS) == set(health.READINESS_CHECKS)


@pytest.mark.parametrize("name", sorted(BREAKERS))
def test_readiness_fails_when_the_dependency_breaks(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # Only the check under test runs: the database breaker would also fail the
    # migrations check whenever its process-wide memo is still unset.
    monkeypatch.setattr(health, "READINESS_CHECKS", {name: health.READINESS_CHECKS[name]})
    BREAKERS[name](monkeypatch)
    assert health.readiness() == [name]


def test_probes_answer_only_get_and_head(client: Client) -> None:
    assert client.head("/healthz").status_code == 200
    assert client.post("/healthz").status_code == 404


@pytest.mark.parametrize(
    ("grant", "ready"),
    [
        ("", True),  # exactly APP_ROLE_GRANTS
        ("GRANT TRUNCATE ON labs_lab TO {role}", False),
        ("GRANT TRIGGER ON audit_rowchange TO {role}", False),
        ("GRANT {owner} TO {role}", False),  # owner privileges through a role
    ],
)
def test_the_runtime_role_check_passes_only_for_the_runtime_role(
    monkeypatch: pytest.MonkeyPatch, grant: str, ready: bool
) -> None:
    roles = Roles("cultures_test_audit", "cultures_test_migration", "cultures_test_runtime")
    monkeypatch.setattr(settings, "DB_RUNTIME_ROLE_REQUIRED", True)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        setup(cursor, roles)
        if grant:
            cursor.execute(grant.format(role=roles.runtime, owner=roles.migration))
        cursor.execute(f"SET LOCAL ROLE {roles.runtime}")
        assert health.check_runtime_role() is ready
        transaction.set_rollback(True)


def test_the_runtime_role_check_is_off_unless_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DB_RUNTIME_ROLE_REQUIRED", False)
    assert health.check_runtime_role() is True  # development connects as the owner

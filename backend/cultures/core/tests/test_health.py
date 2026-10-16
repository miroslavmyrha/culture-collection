import pytest
from django.db.utils import OperationalError
from django.test import Client

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


def test_readiness_fails_with_unapplied_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    class Executor:
        def __init__(self, connection: object) -> None:
            self.loader = type("Loader", (), {"graph": type("Graph", (), {"leaf_nodes": list})()})()

        def migration_plan(self, targets: object) -> list[str]:
            return ["users.0002_pending"]

    monkeypatch.setattr(health, "_migrations_applied", False)
    monkeypatch.setattr(health, "MigrationExecutor", Executor)
    assert health.readiness() == ["migrations"]


def test_probes_answer_only_get_and_head(client: Client) -> None:
    assert client.head("/healthz").status_code == 200
    assert client.post("/healthz").status_code == 404

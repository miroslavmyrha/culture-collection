"""A contract every scoped viewset passes, written once.

A concrete test class in <app>/tests/ names the viewset, its URL and its writes,
and provides four fixtures: `obj` (visible to reader), `reader` (may read obj,
may not write it), `outsider` (sees nothing of obj's scope) and `writer` (may
write `writer_obj`, which defaults to obj). It inherits the matrix: anonymous 401,
outsider 404, list scoped, no internal ids, refused writes change no rows, and
permitted writes answer their status. With `audit_model` set, a refused write
adds no audit row and a permitted one adds exactly one.

core/tests/test_contract_coverage.py fails when a routed viewset has no contract
class, so a new viewset cannot ship without this matrix.
"""

import importlib
import pkgutil
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any, ClassVar

import pytest
from django.apps import apps
from django.db.models import Model
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.views import APIView

from cultures.users.models import User

from .clients import logged_in
from .problems import assert_problem

PROJECT = __name__.split(".")[0] + "."
COVERED: set[type] = set()  # viewsets with a contract class, filled on import


@dataclass(frozen=True)
class Write:
    action: str  # appended to the detail URL: "" for update and destroy, "place/" for an @action
    payload: dict[str, Any]
    changes: type[Model]  # the table a refused write must leave as it was
    method: str = "post"
    status: int = 201


def snapshot(model: type[Model]) -> list[dict[str, Any]]:
    return list(model._default_manager.order_by("pk").values())


class ViewsetContract:
    viewset: ClassVar[type]
    url: ClassVar[str]  # the list URL, with a trailing slash
    writes: ClassVar[tuple[Write, ...]] = ()  # in order: a destroy goes last
    audit_model: ClassVar[type[Model] | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "viewset" in vars(cls):
            COVERED.add(cls.viewset)

    @pytest.fixture
    def writer_obj(self, obj: Any) -> Any:
        """The object the writer changes; override when the writer cannot see obj."""
        return obj

    def detail(self, obj: Any) -> str:
        return f"{self.url}{obj.public_id}/"

    def send(self, user: User | None, obj: Any, write: Write) -> Any:
        method = getattr(logged_in(user), write.method)
        return method(
            f"{self.detail(obj)}{write.action}", write.payload, content_type="application/json"
        )

    def audit_rows(self) -> int:
        return self.audit_model._default_manager.count() if self.audit_model else 0

    def test_anonymous_gets_401(self, obj: Any) -> None:
        for url in (self.url, self.detail(obj)):
            response = logged_in(None).get(url)
            assert_problem(response, 401, "not_authenticated")
            assert response.has_header("WWW-Authenticate")

    def test_list_is_scoped(self, obj: Any, reader: User, outsider: User) -> None:
        def ids(user: User) -> list[str]:
            return [row["public_id"] for row in logged_in(user).get(self.url).json()["results"]]

        assert str(obj.public_id) in ids(reader)
        assert str(obj.public_id) not in ids(outsider)

    def test_detail_answers_404_outside_the_scope(
        self, obj: Any, reader: User, outsider: User
    ) -> None:
        body = logged_in(reader).get(self.detail(obj)).json()
        assert body["public_id"] == str(obj.public_id)
        assert "id" not in body  # internal ids never leave the API
        assert_problem(logged_in(outsider).get(self.detail(obj)), 404, "not_found")

    def test_refused_writes_change_nothing(self, obj: Any, reader: User, outsider: User) -> None:
        refusals = (
            (None, 401, "not_authenticated"),
            (outsider, 404, "not_found"),
            (reader, 403, "permission_denied"),
        )
        for write in self.writes:
            for user, status, code in refusals:
                rows = snapshot(write.changes)
                audit = self.audit_rows()
                assert_problem(self.send(user, obj, write), status, code)
                assert snapshot(write.changes) == rows, (write, user)
                assert self.audit_rows() == audit, (write, user)

    def test_permitted_writes_succeed(self, writer_obj: Any, writer: User) -> None:
        for write in self.writes:
            audit = self.audit_rows()
            response = self.send(writer, writer_obj, write)
            assert response.status_code == write.status, (write, response.content)
            if self.audit_model is not None:
                assert self.audit_rows() == audit + 1, write


def routed_api_views() -> dict[str, type]:
    """Every DRF view of this project in the URLconf, by dotted name.

    Viewsets by class, @api_view functions by function name.
    """
    found: dict[str, type] = {}

    def walk(patterns: list[URLPattern | URLResolver]) -> None:
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns)
                continue
            cls = getattr(pattern.callback, "cls", None)
            if isinstance(cls, type) and issubclass(cls, APIView):
                name = f"{cls.__module__}.{cls.__name__}"
                if name.startswith(PROJECT):
                    found[name] = cls

    walk(get_resolver().url_patterns)
    return found


def import_test_modules() -> None:
    """Import the test modules of every project app, so their contract classes are
    in COVERED also when the coverage test runs alone."""
    for app in apps.get_app_configs():
        package = f"{app.name}.tests"
        if not app.name.startswith(PROJECT) or find_spec(package) is None:
            continue
        for module in pkgutil.iter_modules(importlib.import_module(package).__path__):
            if module.name.startswith("test_"):
                importlib.import_module(f"{package}.{module.name}")

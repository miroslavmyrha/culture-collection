"""The shared role matrix (core.testing.ViewsetContract) for the storage unit viewset.

core/tests/test_contract_coverage.py fails while a routed viewset has no such class. The
writes here are the detail actions; create and the per-role matrix of every action are in
test_api_permissions.py. The box types are global reference data, listed in EXEMPT there
with test_api.py, which calls them.
"""

from typing import Any

import pytest

from cultures.audit.models import AuditEvent
from cultures.core.testing import ViewsetContract, Write, assert_problem, logged_in
from cultures.storage.api.views import StorageUnitViewSet
from cultures.storage.models import StorageUnit
from cultures.users.models import User

from .conftest import UNITS_URL, Tree

pytestmark = pytest.mark.django_db


class TestStorageUnitContract(ViewsetContract):
    viewset = StorageUnitViewSet
    url = UNITS_URL
    audit_model = AuditEvent
    writes = (
        Write("edit/", {"name": "Rack 1a"}, changes=StorageUnit, status=200),
        Write(
            "status/",
            {"status": "out_of_service", "reason": "alarm"},
            changes=StorageUnit,
            status=200,
        ),
        Write("move/", {}, changes=StorageUnit, status=400),
    )

    @pytest.fixture
    def obj(self, tree: Tree) -> StorageUnit:
        return tree.rack

    @pytest.fixture
    def reader(self, viewer: User) -> User:
        return viewer

    @pytest.fixture
    def writer(self, curator: User) -> User:
        return curator

    # The list is the lab's whole tree, not paged, under a lab the outsider is not a member
    # of: the whole list is a 404.
    def test_list_is_scoped(self, obj: Any, reader: User, outsider: User) -> None:
        listed = logged_in(reader).get(self.url).json()
        assert str(obj.public_id) in [row["public_id"] for row in listed]
        assert_problem(logged_in(outsider).get(self.url), 404, "not_found")

    # The move write above has an empty body: a permitted caller gets 400 and no event.
    def test_permitted_writes_succeed(self, writer_obj: Any, writer: User) -> None:
        for write in self.writes:
            audit = self.audit_rows()
            response = self.send(writer, writer_obj, write)
            assert response.status_code == write.status, (write, response.content)
            assert self.audit_rows() == audit + (1 if write.status < 400 else 0), write

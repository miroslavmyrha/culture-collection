"""The shared role matrix (core.testing.ViewsetContract) for the passage, batch, check and vial
viewsets. core/tests/test_contract_coverage.py fails while a routed viewset has no such class.
The writes here are the detail actions; create and every action per role are in
test_api_permissions.py."""

from typing import Any, ClassVar

import pytest

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.core.testing import ViewsetContract, Write, assert_problem, logged_in
from cultures.lineage.api.views import BatchCheckViewSet, BatchViewSet, PassageViewSet, VialViewSet
from cultures.lineage.models import Batch, BatchCheck, Passage, Vial
from cultures.users.models import User

from .support import BATCHES_URL, CHECKS_URL, PASSAGES_URL, VIALS_URL, MakeBatch, record, vials_of

pytestmark = pytest.mark.django_db


class Readers:
    url: ClassVar[str]

    # Under a lab the outsider is not a member of: the whole list is a 404.
    def test_list_is_scoped(self, obj: Any, reader: User, outsider: User) -> None:
        listed = logged_in(reader).get(self.url).json()["results"]
        assert str(obj.public_id) in [row["public_id"] for row in listed]
        assert_problem(logged_in(outsider).get(self.url), 404, "not_found")

    @pytest.fixture
    def reader(self, viewer: User) -> User:
        return viewer

    @pytest.fixture
    def writer(self, technician: User) -> User:
        return technician


class TestPassageContract(Readers, ViewsetContract):
    viewset = PassageViewSet
    url = PASSAGES_URL

    @pytest.fixture
    def obj(self, passage0: Passage) -> Passage:
        return passage0


class TestBatchContract(Readers, ViewsetContract):
    viewset = BatchViewSet
    url = BATCHES_URL

    @pytest.fixture
    def obj(self, make_batch: MakeBatch, passage0: Passage) -> Batch:
        return make_batch(passage0, vial_count=1)


class TestVialContract(Readers, ViewsetContract):
    viewset = VialViewSet
    url = VIALS_URL
    audit_model = AuditEvent
    # Place needs a box id from a fixture: it is in test_api_permissions.py with the others.
    writes = (
        Write("barcode/", {"barcode": "TUBE-1"}, changes=Vial, status=200),
        Write("status/", {"status": "lost", "reason": "gone"}, changes=Vial, status=200),
    )

    @pytest.fixture
    def obj(self, make_batch: MakeBatch, passage0: Passage) -> Vial:
        return vials_of(make_batch(passage0, vial_count=1))[0]


class TestBatchDecisionContract(Readers, ViewsetContract):
    """Holding a batch is the curators': a technician reads it and is refused (403)."""

    viewset = BatchViewSet
    url = BATCHES_URL
    audit_model = AuditEvent
    writes = (Write("hold/", {"reason": "a doubt about its purity"}, changes=Batch, status=200),)

    @pytest.fixture
    def obj(self, make_batch: MakeBatch, passage0: Passage) -> Batch:
        return make_batch(passage0, vial_count=1)

    @pytest.fixture
    def reader(self, technician: User) -> User:
        return technician

    @pytest.fixture
    def writer(self, curator: User) -> User:
        return curator


class TestBatchCheckContract(Readers, ViewsetContract):
    viewset = BatchCheckViewSet
    url = CHECKS_URL
    audit_model = AuditEvent
    writes = (
        Write("enter-in-error/", {"reason": "the wrong batch"}, changes=BatchCheck, status=200),
    )

    @pytest.fixture
    def obj(self, make_batch: MakeBatch, passage0: Passage, technician: User) -> BatchCheck:
        batch = make_batch(passage0, vial_count=1)
        with audit_context(channel=Channel.API, actor=technician, request_id="req-setup"):
            return record(technician, batch)

"""The shared role matrix (core.testing.ViewsetContract) for the depositor, MTA template and
deposit viewsets. core/tests/test_contract_coverage.py fails while a routed viewset has
none. The per-role matrix of every action is in test_api_permissions.py.

The reader is the technician: a member of the lab who sees no deposit (deposits.view is
for curators and managers), so the list answers 403 for them rather than an empty page."""

from typing import Any

import pytest

from cultures.audit.models import AuditEvent
from cultures.core.testing import ViewsetContract, Write, assert_problem, logged_in
from cultures.core.testing.contract import snapshot
from cultures.deposits.api.views import DepositorViewSet, DepositViewSet, MtaTemplateViewSet
from cultures.deposits.models import Deposit, Depositor, MtaTemplate
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.users.models import User

from .support import DEPOSITORS_URL, DEPOSITS_URL, MTA_URL, MakeDeposit

pytestmark = pytest.mark.django_db


class LabContract(ViewsetContract):
    """A curator reads; a technician of the same lab is refused; the outsider sees nothing."""

    @pytest.fixture
    def reader(self, curator: User) -> User:
        return curator

    # The contract's reader may read but not write. Here reading and writing go together
    # (deposits.view and deposits.manage are both a curator's), so the refusal comes from
    # the technician, a member who sees no row of these kinds: 404 for a row, like any row
    # a caller cannot see.
    def test_refused_writes_change_nothing(self, obj: Any, reader: User, outsider: User) -> None:
        technician = member_of(obj.lab, Role.TECHNICIAN, "contract-technician")
        refusals = (
            (None, 401, "not_authenticated"),
            (outsider, 404, "not_found"),
            (technician, 404, "not_found"),
        )
        for write in self.writes:
            for user, status, code in refusals:
                rows = snapshot(write.changes)
                audit = self.audit_rows()
                assert_problem(self.send(user, obj, write), status, code)
                assert snapshot(write.changes) == rows, (write, user)
                assert self.audit_rows() == audit, (write, user)

    # The list is nested under a lab the outsider is not a member of: the whole list is a 404.
    def test_list_is_scoped(self, obj: Any, reader: User, outsider: User) -> None:
        listed = logged_in(reader).get(self.url).json()["results"]
        assert str(obj.public_id) in [row["public_id"] for row in listed]
        assert_problem(logged_in(outsider).get(self.url), 404, "not_found")


class TestDepositorContract(LabContract):
    viewset = DepositorViewSet
    url = DEPOSITORS_URL
    audit_model = AuditEvent
    writes = (
        Write(
            "",
            {"name": "Jana Vzorová", "institution": "Other"},
            changes=Depositor,
            method="put",
            status=200,
        ),
    )

    @pytest.fixture
    def obj(self, depositor: Depositor) -> Depositor:
        return depositor

    @pytest.fixture
    def writer(self, curator: User) -> User:
        return curator


class TestMtaTemplateContract(LabContract):
    viewset = MtaTemplateViewSet
    url = MTA_URL
    audit_model = AuditEvent

    @pytest.fixture
    def obj(self, mta: MtaTemplate) -> MtaTemplate:
        return mta

    @pytest.fixture
    def writer(self, manager: User) -> User:
        return manager


class TestDepositContract(LabContract):
    viewset = DepositViewSet
    url = DEPOSITS_URL
    audit_model = AuditEvent
    # In order: the check starts, then the deposit is rejected. Acceptance, with its three
    # events, is in test_api_permissions.py and test_api.py.
    writes = (
        Write("start-check/", {}, changes=Deposit, status=200),
        Write("reject/", {"reason": "mixed culture"}, changes=Deposit, status=200),
    )

    @pytest.fixture
    def obj(self, make_deposit: MakeDeposit) -> Deposit:
        return make_deposit()

    @pytest.fixture
    def writer(self, curator: User) -> User:
        return curator

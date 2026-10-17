"""The shared role matrix (core.testing.ViewsetContract) for both labs viewsets.

core/tests/test_contract_coverage.py fails while a routed viewset has no such class.
The per-action, per-role matrix is in test_api_members.py and test_api_labs.py.
"""

import pytest

from cultures.audit.models import AuditEvent
from cultures.core.testing import ViewsetContract, Write, assert_problem, logged_in
from cultures.labs.api.views import LabViewSet, MemberViewSet
from cultures.labs.models import Lab, Membership
from cultures.users.models import User

from .conftest import LABS_URL, MEMBERS_URL, membership

pytestmark = pytest.mark.django_db


class TestLabContract(ViewsetContract):
    viewset = LabViewSet
    url = LABS_URL
    writes = ()  # labs are created and changed in Django admin only (test_api_labs.py)

    @pytest.fixture
    def obj(self, lab: Lab) -> Lab:
        return lab

    @pytest.fixture
    def reader(self, viewer: User) -> User:
        return viewer

    @pytest.fixture
    def writer(self, manager: User) -> User:
        return manager


class TestMemberContract(ViewsetContract):
    viewset = MemberViewSet
    url = MEMBERS_URL
    audit_model = AuditEvent
    writes = (
        Write("", {"role": "curator"}, changes=Membership, method="put", status=200),
        Write("", {"role": "viewer"}, changes=Membership, method="patch", status=200),
        Write("", {}, changes=Membership, method="delete", status=204),
    )

    @pytest.fixture
    def obj(self, lab: Lab, technician: User) -> Membership:
        return membership(technician, lab)

    @pytest.fixture
    def reader(self, viewer: User) -> User:
        return viewer

    @pytest.fixture
    def writer(self, manager: User) -> User:
        return manager

    # The base test reads the outsider's list as a page. Here the list is nested under a
    # lab the outsider is not a member of, so the whole list answers 404, like its detail.
    def test_list_is_scoped(self, obj: Membership, reader: User, outsider: User) -> None:
        listed = logged_in(reader).get(self.url).json()["results"]
        assert str(obj.public_id) in [row["public_id"] for row in listed]
        assert_problem(logged_in(outsider).get(self.url), 404, "not_found")

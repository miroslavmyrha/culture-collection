"""The shared role matrix (core.testing.ViewsetContract) for the requester, permit, document,
request and shipment document viewsets. core/tests/test_contract_coverage.py fails while a
routed viewset has none. The per-role matrix of every action is in test_api_permissions.py."""

from typing import Any

import pytest

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent
from cultures.core.testing import ViewsetContract, Write, assert_problem, logged_in
from cultures.core.testing.contract import snapshot
from cultures.distribution.api.views import (
    DocumentViewSet,
    PermitViewSet,
    RequesterViewSet,
    RequestViewSet,
    ShipmentDocumentViewSet,
)
from cultures.distribution.models import (
    DistributionRequest,
    Document,
    PermitKind,
    RecipientPermit,
    Requester,
    ShipmentDocument,
)
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.users.models import User

from .support import (
    DOCUMENTS_URL,
    LAB_URL,
    PERMITS_URL,
    REQUESTERS_URL,
    REQUESTS_URL,
    Supply,
    accept_mtas,
    add_permit,
    approve,
    ship,
    submit,
)

pytestmark = pytest.mark.django_db

REQUESTER_BODY = {
    "institution": "Renamed Institute",
    "legal_form": "legal_person",
    "seat": "Vzorová 14, 602 00 Brno",
    "country": "CZ",
    "lab_evidence": "Seen on the department page.",
    "lab_confirmed_on": "2026-10-01",
    "name": "Petra Ukázková",
    "postal_address": "Testovací 5, Brno",
}


class PeopleContract(ViewsetContract):
    """A curator reads and writes; a technician of the same lab sees no row of these kinds
    (they reach people): 404 for a row, like any row a caller cannot see."""

    @pytest.fixture
    def reader(self, curator: User) -> User:
        return curator

    @pytest.fixture
    def writer(self, curator: User) -> User:
        return curator

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


class TestRequesterContract(PeopleContract):
    viewset = RequesterViewSet
    url = REQUESTERS_URL
    audit_model = AuditEvent
    writes = (Write("", REQUESTER_BODY, changes=Requester, method="put", status=200),)

    @pytest.fixture
    def obj(self, requester: Requester) -> Requester:
        return requester


class TestPermitContract(PeopleContract):
    viewset = PermitViewSet
    url = PERMITS_URL
    audit_model = AuditEvent
    writes = (
        Write(
            "end/",
            {"ended_on": "2026-06-01", "reason": "revoked"},
            changes=RecipientPermit,
            status=200,
        ),
    )

    @pytest.fixture
    def obj(self, as_curator: AuditContext, curator: User, requester: Requester) -> RecipientPermit:
        return add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE)


class TestDocumentContract(PeopleContract):
    """A file, read one at a time: no list, and the answer is the file, not a JSON body."""

    viewset = DocumentViewSet
    url = DOCUMENTS_URL

    @pytest.fixture
    def obj(self, as_curator: AuditContext, curator: User, requester: Requester) -> Document:
        return add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE).document

    def test_anonymous_gets_401(self, obj: Any) -> None:
        response = logged_in(None).get(self.detail(obj))
        assert_problem(response, 401, "not_authenticated")
        assert response.has_header("WWW-Authenticate")

    def test_list_is_scoped(self, obj: Any, reader: User, outsider: User) -> None:
        assert logged_in(reader).get(self.url).status_code == 404  # not routed: no list
        assert_problem(logged_in(outsider).get(self.detail(obj)), 404, "not_found")

    def test_detail_answers_404_outside_the_scope(
        self, obj: Any, reader: User, outsider: User
    ) -> None:
        response = logged_in(reader).get(self.detail(obj))
        assert response.status_code == 200
        assert response["Content-Disposition"] == (
            f'attachment; filename="document-{obj.public_id}.pdf"'
        )
        assert_problem(logged_in(outsider).get(self.detail(obj)), 404, "not_found")


class TestShipmentDocumentContract(PeopleContract):
    """A document of a shipment (#90), read one at a time: no list, no write."""

    viewset = ShipmentDocumentViewSet
    url = f"{LAB_URL}/shipment-documents/"

    @pytest.fixture
    def obj(
        self,
        as_curator: AuditContext,
        curator: User,
        lab: Lab,
        requester: Requester,
        supply: Supply,
    ) -> ShipmentDocument:
        request = submit(curator, lab, requester, [(supply(), 1)])
        accept_mtas(curator, request)
        approve(curator, request)
        ship(curator, request)
        return ShipmentDocument.objects.get(shipment__request=request)

    def test_anonymous_gets_401(self, obj: Any) -> None:
        response = logged_in(None).get(self.detail(obj))
        assert_problem(response, 401, "not_authenticated")
        assert response.has_header("WWW-Authenticate")

    def test_list_is_scoped(self, obj: Any, reader: User, outsider: User) -> None:
        assert logged_in(reader).get(self.url).status_code == 404  # not routed: no list
        assert_problem(logged_in(outsider).get(self.detail(obj)), 404, "not_found")


class TestRequestContract(ViewsetContract):
    """A viewer reads a request; deciding on it is the curators'."""

    viewset = RequestViewSet
    url = REQUESTS_URL
    audit_model = AuditEvent
    writes = (
        Write("reject/", {"reason": "no laboratory"}, changes=DistributionRequest, status=200),
    )

    @pytest.fixture
    def obj(
        self,
        as_curator: AuditContext,
        curator: User,
        lab: Lab,
        requester: Requester,
        supply: Supply,
    ) -> DistributionRequest:
        return submit(curator, lab, requester, [(supply(), 1)])

    @pytest.fixture
    def reader(self, viewer: User) -> User:
        return viewer

    @pytest.fixture
    def writer(self, curator: User) -> User:
        return curator

    def test_list_is_scoped(self, obj: Any, reader: User, outsider: User) -> None:
        listed = logged_in(reader).get(self.url).json()["results"]
        assert str(obj.public_id) in [row["public_id"] for row in listed]
        assert_problem(logged_in(outsider).get(self.url), 404, "not_found")

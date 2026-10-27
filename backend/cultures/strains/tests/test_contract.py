"""The shared role matrix (core.testing.ViewsetContract) for the strain viewset.

core/tests/test_contract_coverage.py fails while a routed viewset has no such class. The
writes here are the detail actions; create and the per-role matrix of every action are in
test_api_permissions.py.
"""

from typing import Any

import pytest

from cultures.audit.models import AuditEvent
from cultures.core.testing import ViewsetContract, Write, assert_problem, logged_in
from cultures.strains.api.views import StrainViewSet
from cultures.strains.models import Strain, StrainIdentification, StrainRestriction
from cultures.users.models import User

from .conftest import GMO, STRAINS_URL, MakeStrain

pytestmark = pytest.mark.django_db


class TestStrainContract(ViewsetContract):
    viewset = StrainViewSet
    url = STRAINS_URL
    audit_model = AuditEvent
    writes = (
        Write("risk-group/", {"risk_group": 2, "reason": "reassessed"}, changes=Strain, status=200),
        Write(
            "growth/",
            {"temperature_low_c": 30, "atmosphere": "aerobic", "reason": "from the sheet"},
            changes=Strain,
            status=200,
        ),
        Write(
            "restrictions/",
            {"kind": "cz_rat", "reference": "Příloha 2, bod 3", "reason": "listed"},
            changes=StrainRestriction,
            status=200,
        ),
        Write("reclassify/", {}, changes=StrainIdentification, status=400),
    )

    @pytest.fixture
    def obj(self, make_strain: MakeStrain) -> Strain:
        return make_strain(restrictions=[GMO])

    @pytest.fixture
    def reader(self, viewer: User) -> User:
        return viewer

    @pytest.fixture
    def writer(self, curator: User) -> User:
        return curator

    # The list is nested under a lab the outsider is not a member of: the whole list is a 404.
    def test_list_is_scoped(self, obj: Any, reader: User, outsider: User) -> None:
        listed = logged_in(reader).get(self.url).json()["results"]
        assert str(obj.public_id) in [row["public_id"] for row in listed]
        assert_problem(logged_in(outsider).get(self.url), 404, "not_found")

    # The reclassify write above has an empty body: a permitted caller gets 400 and no event.
    def test_permitted_writes_succeed(self, writer_obj: Any, writer: User) -> None:
        for write in self.writes:
            audit = self.audit_rows()
            response = self.send(writer, writer_obj, write)
            assert response.status_code == write.status, (write, response.content)
            assert self.audit_rows() == audit + (1 if write.status < 400 else 0), write

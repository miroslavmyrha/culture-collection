"""As the runtime role (ADR 0005): the whole of distribution works, deletes do not, and the guard
triggers hold for it as for everybody. Grants come from audit.roles.APP_ROLE_GRANTS;
audit/tests/test_roles.py compares every table with it, this proves what distribution needs."""

import pytest
from django.db.backends.utils import CursorWrapper

from cultures.audit.context import AuditContext
from cultures.audit.models import RowChange
from cultures.audit.tests.conftest import TEST_ROLES, refused
from cultures.distribution import services
from cultures.distribution.models import (
    ClassificationBasis,
    PackingInstruction,
    PermitKind,
    Requester,
    TransportClass,
)
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.users.models import User

from .support import Supply, accept_mtas, add_permit, approve, shipment_input, submit

pytestmark = pytest.mark.django_db
TABLES = (
    "distribution_requester",
    "distribution_document",
    "distribution_recipientpermit",
    "distribution_requestcounter",
    "distribution_distributionrequest",
    "distribution_requestline",
    "distribution_linepermit",
    "distribution_mtaacceptance",
    "distribution_vialreservation",
    "distribution_shipment",
    "distribution_shipmentvial",
)


def test_the_runtime_role_enters_approves_ships_and_cancels(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    runtime_role: CursorWrapper,
) -> None:
    strain = supply(risk_group=2)
    runtime_role.execute("SELECT current_user")
    assert runtime_role.fetchone() == (TEST_ROLES.runtime,)
    permit = add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT)
    request = submit(curator, lab, requester, [(strain, 2)])
    accept_mtas(curator, request)
    approve(curator, request)
    services.request_cancel(access=access_for(curator), request=request, reason="withdrawn")
    shipped = submit(curator, lab, requester, [(strain, 1)])
    accept_mtas(curator, shipped)
    approve(curator, shipped)
    services.request_ship(
        access=access_for(curator),
        request=shipped,
        data=shipment_input(
            transport_class=TransportClass.UN3373,
            classification_basis=ClassificationBasis.INDICATIVE_LIST,
            packing_instruction=PackingInstruction.P650,
        ),
    )
    services.permit_end(
        access=access_for(curator), permit=permit, ended_on=permit.valid_from, reason="revoked"
    )
    labels = set(RowChange.objects.values_list("table_label", flat=True))
    assert {f"distribution.{t.removeprefix('distribution_')}" for t in TABLES} <= labels


@pytest.mark.parametrize("table", TABLES)
def test_the_runtime_role_deletes_nothing(table: str, runtime_role: CursorWrapper) -> None:
    refused(runtime_role, f"DELETE FROM {table}", "permission denied")  # noqa: S608 (a test literal)


@pytest.mark.parametrize(
    "table",
    [
        "distribution_document",
        "distribution_requestline",
        "distribution_linepermit",
        "distribution_mtaacceptance",
        "distribution_shipment",
        "distribution_shipmentvial",
    ],
)
def test_frozen_tables_take_no_update_from_the_runtime_role(
    table: str, runtime_role: CursorWrapper
) -> None:
    refused(runtime_role, f"UPDATE {table} SET id = id", "permission denied")  # noqa: S608

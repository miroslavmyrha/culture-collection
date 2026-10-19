"""As the runtime role (ADR 0005): the intake works from receipt to passage 0, deletes do
not, and the guard triggers hold for it as for everybody. Grants come from
audit.roles.APP_ROLE_GRANTS; test_roles.py compares every table with it."""

import pytest
from django.db.backends.utils import CursorWrapper

from cultures.audit.context import AuditContext
from cultures.audit.models import RowChange
from cultures.audit.tests.conftest import TEST_ROLES, refused
from cultures.deposits import services
from cultures.labs.access import Access
from cultures.lineage.models import Passage
from cultures.taxonomy.models import Taxon

from .support import MakeDeposit, facts

pytestmark = pytest.mark.django_db

TABLES = [
    "deposits_contact",
    "deposits_depositor",
    "deposits_mtatemplate",
    "deposits_deposit",
    "deposits_depositterms",
    "deposits_termsuse",
    "lineage_passage",
]


def test_the_runtime_role_takes_a_deposit_to_its_strain(
    as_curator: AuditContext,
    curator_access: Access,
    make_deposit: MakeDeposit,
    exempli: Taxon,
    runtime_role: CursorWrapper,
) -> None:
    runtime_role.execute("SELECT current_user")
    assert runtime_role.fetchone() == (TEST_ROLES.runtime,)
    deposit = make_deposit("checking")
    services.deposit_accept(access=curator_access, deposit=deposit, facts=facts(exempli))
    services.contact_erase(contact=deposit.depositor.contact, reason="erasure request")
    assert Passage.objects.get().source_deposit == deposit
    labels = set(RowChange.objects.values_list("table_label", flat=True))
    assert {
        "deposits.deposit",
        "deposits.depositterms",
        "deposits.termsuse",
        "lineage.passage",
    } <= labels
    assert not any(label.startswith("deposits.contact") for label in labels)


@pytest.mark.parametrize("table", TABLES)
def test_the_runtime_role_deletes_nothing_of_the_intake(
    *,
    make_deposit: MakeDeposit,
    exempli: Taxon,
    runtime_role: CursorWrapper,
    table: str,
) -> None:
    make_deposit("accepted", taxon=exempli)
    refused(runtime_role, f"DELETE FROM {table}", f"permission denied for table {table}")  # noqa: S608
    refused(runtime_role, f"TRUNCATE {table}", f"permission denied for table {table}")


DENIED = "permission denied for table"


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("UPDATE deposits_mtatemplate SET title = 'x'", f"{DENIED} deposits_mtatemplate"),
        ("UPDATE deposits_termsuse SET decision = 'deny'", f"{DENIED} deposits_termsuse"),
        ("UPDATE lineage_passage SET number = 3", f"{DENIED} lineage_passage"),
        (
            "UPDATE deposits_deposit SET name_as_received = 'x' WHERE status = 'received'",
            "the receipt of a deposit never changes",
        ),
        (
            "UPDATE deposits_deposit SET status = 'received' WHERE status = 'accepted'",
            "a decided deposit never changes",
        ),
        (
            "UPDATE deposits_depositterms SET is_active = true, abs_scope = 'unknown'",
            "only stops being active",
        ),
    ],
)
def test_the_guards_and_grants_hold_for_the_runtime_role(
    *,
    make_deposit: MakeDeposit,
    mta: object,
    exempli: Taxon,
    runtime_role: CursorWrapper,
    statement: str,
    message: str,
) -> None:
    make_deposit("accepted", taxon=exempli)
    make_deposit()
    refused(runtime_role, statement, message)

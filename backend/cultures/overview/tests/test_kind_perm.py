"""KIND_PERM is the one rule of who sees each kind (#69): every kind has an entry, and in a lab
a role sees the kind exactly when it holds that permission there. Each case makes one item of its
kind through the services and asks every role of the lab, and a person who holds every
permission elsewhere but only views here."""

from collections.abc import Callable
from datetime import timedelta

import pytest

from cultures.biosafety.models import AuthorisationKind
from cultures.biosafety.policy import permit_today
from cultures.deposits.tests.support import MakeDeposit
from cultures.distribution.models import PermitKind, Requester
from cultures.distribution.tests.support import (
    Regulated,
    Supply,
    accept_mtas,
    add_permit,
    approve,
    as_actor,
    submit,
)
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import RANK, ROLES, Role, role_has
from cultures.labs.tests.conftest import member_of
from cultures.lineage import services as lineage
from cultures.lineage.models import Batch, VialStatus
from cultures.lineage.tests.support import pass_all, vials_of
from cultures.overview.selectors import KIND_PERM, Kind
from cultures.strains.tests.conftest import make_permit
from cultures.users.models import User

from .support import waiting

pytestmark = pytest.mark.django_db

Make = Callable[[], None]


def test_every_kind_has_a_permission() -> None:
    assert set(KIND_PERM) == set(Kind)


# The lowest role each kind waits for, as the owner decided it (#69). Spelled out, so a change of
# KIND_PERM that lets another role see a kind fails here, not only where the table is read.
LOWEST: dict[Kind, Role] = {
    Kind.DEPOSIT_RECEIVED: Role.CURATOR,
    Kind.DEPOSIT_CHECKING: Role.CURATOR,
    Kind.BATCH_CHECKS_MISSING: Role.TECHNICIAN,
    Kind.BATCH_TO_RELEASE: Role.CURATOR,
    Kind.BATCH_ON_HOLD: Role.CURATOR,
    Kind.REQUEST_TO_DECIDE: Role.CURATOR,
    Kind.SHIPMENT_TO_CONFIRM: Role.CURATOR,
    Kind.REQUEST_TO_SHIP: Role.CURATOR,
    Kind.RECIPIENT_PERMIT_EXPIRING: Role.MANAGER,
    Kind.LAB_PERMIT_EXPIRING: Role.MANAGER,
    Kind.VIALS_TO_DESTROY: Role.CURATOR,
}


@pytest.mark.parametrize("kind", list(Kind))
def test_each_kind_waits_for_the_roles_the_owner_named(kind: Kind) -> None:
    for role in ROLES:
        assert role_has(role, KIND_PERM[kind]) == (RANK[role] >= RANK[LOWEST[kind]]), role


@pytest.fixture
def make_one(
    *,
    make_deposit: MakeDeposit,
    supply: Supply,
    regulated: Regulated,
    requester: Requester,
    lab: Lab,
    curator: User,
    approver: User,
) -> dict[Kind, Make]:
    """One item of each kind in `lab`, made through the services."""
    today = permit_today()

    def batch() -> Batch:
        return Batch.objects.get(strain=supply(release=False))

    def released() -> None:
        with as_actor(curator):
            pass_all(curator, batch())

    def held() -> None:
        made = Batch.objects.get(strain=supply())
        with as_actor(curator):
            lineage.batch_hold(access=access_for(curator), batch=made, reason="Mould.")

    def to_ship() -> None:
        request = submit(curator, lab, requester, [(supply(), 1)])
        accept_mtas(curator, request)
        approve(curator, request)

    def to_destroy() -> None:
        vial = vials_of(batch())[0]
        with as_actor(curator):
            lineage.vial_transition(
                access=access_for(curator),
                vial=vial,
                status=VialStatus.TO_DESTROY,
                reason="Cracked.",
            )

    soon = today + timedelta(days=5)
    return {
        Kind.DEPOSIT_RECEIVED: lambda: void(make_deposit()),
        Kind.DEPOSIT_CHECKING: lambda: void(make_deposit("checking")),
        Kind.BATCH_CHECKS_MISSING: lambda: void(batch()),
        Kind.BATCH_TO_RELEASE: released,
        Kind.BATCH_ON_HOLD: held,
        Kind.REQUEST_TO_DECIDE: lambda: void(submit(curator, lab, requester, [(supply(), 1)])),
        # Approved and prepared by the approver: every other holder of the permission confirms.
        Kind.SHIPMENT_TO_CONFIRM: lambda: void(regulated(prepared_by=approver)),
        Kind.REQUEST_TO_SHIP: to_ship,
        Kind.RECIPIENT_PERMIT_EXPIRING: lambda: void(
            add_permit(
                curator,
                requester,
                PermitKind.SUJB_RAT_NOTICE,
                valid_from=today - timedelta(days=9),
                expires_on=soon,
            )
        ),
        Kind.LAB_PERMIT_EXPIRING: lambda: void(
            make_permit(lab, AuthorisationKind.CZ_VRAT, expires_on=soon)
        ),
        Kind.VIALS_TO_DESTROY: to_destroy,
    }


def void(_: object) -> None:
    """Drops what a maker returns."""


@pytest.mark.parametrize("kind", list(Kind))
def test_a_role_sees_a_kind_exactly_when_it_holds_its_permission_in_that_lab(
    kind: Kind, make_one: dict[Kind, Make], team: dict[Role, User], lab: Lab, other_lab: Lab
) -> None:
    elsewhere = member_of(other_lab, Role.MANAGER, "manager-elsewhere")
    Membership.objects.create(user=elsewhere, lab=lab, role=Role.VIEWER)
    make_one[kind]()
    for role, user in team.items():
        assert (kind in waiting(user)) == role_has(role, KIND_PERM[kind]), role
    assert kind not in waiting(elsewhere)

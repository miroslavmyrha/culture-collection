"""Fixtures of the lineage tests: strains that came from accepted deposits (so each has its
passage 0), one of them regulated, and batches preserved through the service."""

from collections.abc import Iterator
from typing import Any

import pytest

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import Channel
from cultures.deposits import services as deposits
from cultures.deposits.models import Deposit
from cultures.deposits.tests.support import DUAL_USE, MakeDeposit, as_actor, facts
from cultures.labs import services as labs
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of, membership
from cultures.lineage.models import Batch, Passage
from cultures.strains.models import Strain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import MakeBatch, preserve


@pytest.fixture
def strain(make_deposit: MakeDeposit, exempli: Taxon) -> Strain:
    """Testella exempli, risk group 1, from an accepted deposit: its passage 0 exists."""
    deposit: Deposit = make_deposit("accepted", taxon=exempli)
    assert deposit.strain is not None
    return deposit.strain


@pytest.fixture
def passage0(strain: Strain) -> Passage:
    return Passage.objects.get(strain=strain, number=0)


@pytest.fixture
def regulated(make_deposit: MakeDeposit, mockia: Taxon, curator: User) -> Strain:
    """Mockia vulgaris (invented), with a dual-use restriction: its locations are masked."""
    deposit: Deposit = make_deposit("checking", name_as_received="Mockia vulgaris D2")
    with as_actor(curator):
        accepted = deposits.deposit_accept(
            access=access_for(curator),
            deposit=deposit,
            facts=facts(mockia, restrictions=[DUAL_USE]),
        )
    assert accepted.strain is not None
    return accepted.strain


@pytest.fixture
def make_batch(curator: User) -> MakeBatch:
    """A batch preserved by the curator through the service, in its own audit context."""

    def make(passage: Passage, actor: User = curator, **changes: Any) -> Batch:
        with audit_context(channel=Channel.API, actor=actor, request_id="req-setup"):
            return preserve(actor, passage, **changes)

    return make


@pytest.fixture
def as_technician(technician: User) -> Iterator[AuditContext]:
    with audit_context(channel=Channel.API, actor=technician, request_id="req-1") as context:
        yield context


@pytest.fixture
def keeper(lab: Lab, manager: User) -> User:
    """A viewer who holds the lab's location grant, given by the manager."""
    user = member_of(lab, Role.VIEWER, "keeper")
    with audit_context(channel=Channel.API, actor=manager, request_id="req-setup"):
        labs.location_grant_add(
            access=access_for(manager),
            lab=lab,
            membership=membership(user, lab),
            reason="keeps the register",
        )
    return user

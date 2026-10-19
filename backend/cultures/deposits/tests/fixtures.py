"""Fixtures of the deposits tests: a depositor, an MTA version and deposits in each state,
all made through the services."""

from datetime import date
from typing import Any

import pytest

from cultures.deposits import services
from cultures.deposits.models import Condition, Deposit, Depositor, MtaTemplate
from cultures.deposits.services import NewDeposit
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import JANA, ContactInput, MakeDeposit, MakeDepositor, as_actor, facts, terms


@pytest.fixture
def make_depositor(lab: Lab, curator: User) -> MakeDepositor:
    def make(
        lab: Lab = lab, actor: User = curator, contact: ContactInput = JANA, institution: str = ""
    ) -> Depositor:
        with as_actor(actor):
            return services.depositor_create(
                access=access_for(actor), lab=lab, contact=contact, institution=institution
            )

    return make


@pytest.fixture
def depositor(make_depositor: MakeDepositor) -> Depositor:
    return make_depositor(institution="Example University")


@pytest.fixture
def mta(lab: Lab, manager: User) -> MtaTemplate:
    with as_actor(manager):
        return services.mta_template_publish(
            access=access_for(manager), lab=lab, code="STD", title="Standard MTA", text="Terms."
        )


@pytest.fixture
def make_deposit(lab: Lab, curator: User, depositor: Depositor) -> MakeDeposit:
    """A deposit taken to the state asked for, through the services, by the curator."""

    def make(
        state: str = "received",
        *,
        taxon: Taxon | None = None,
        actor: User = curator,
        **changes: Any,
    ) -> Deposit:
        values: dict[str, Any] = {
            "depositor": depositor,
            "received_on": date(2026, 10, 1),
            "condition": Condition.INTACT,
            "name_as_received": "Testella exempli D1",
            "terms": terms(),
            **changes,
        }
        access = access_for(actor)
        with as_actor(actor):
            deposit = services.deposit_receive(access=access, lab=lab, data=NewDeposit(**values))
            if state in ("checking", "accepted", "rejected"):
                deposit = services.deposit_start_check(access=access, deposit=deposit)
            if state == "accepted":
                assert taxon is not None, "an accepted deposit needs a taxon"
                deposit = services.deposit_accept(
                    access=access, deposit=deposit, facts=facts(taxon)
                )
            if state == "rejected":
                deposit = services.deposit_reject(access=access, deposit=deposit, reason="mixed")
        deposit.refresh_from_db()
        return deposit

    return make

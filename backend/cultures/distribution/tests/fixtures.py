"""Fixtures of the distribution tests: strains supplied from released distribution batches,
requesters, all made through the services."""

from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest

from cultures.biosafety.models import AuthorisationKind, RestrictionKind
from cultures.deposits import services as deposits
from cultures.deposits.models import Condition, Depositor, MtaTemplate
from cultures.deposits.tests.support import DUAL_USE, facts, terms
from cultures.distribution import services
from cultures.distribution.models import DistributionRequest, PermitKind, Requester
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.lineage import services as lineage
from cultures.lineage.models import Passage, Purpose
from cultures.lineage.tests.support import pass_all, preserve
from cultures.strains.models import Strain
from cultures.strains.services import RestrictionInput
from cultures.strains.tests.conftest import make_permit
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import (
    MakeRequester,
    Regulated,
    Supply,
    accept_mtas,
    add_permit,
    approve,
    as_actor,
    prepare,
    requester_input,
    submit,
)

NEEDS_LAB_PERMIT = {
    RestrictionKind.CZ_VRAT: AuthorisationKind.CZ_VRAT,
    RestrictionKind.QUARANTINE_PEST: AuthorisationKind.QUARANTINE_PEST,
}


@pytest.fixture
def supply(
    lab: Lab, curator: User, depositor: Depositor, mta: MtaTemplate, exempli: Taxon
) -> Supply:
    """A strain from an accepted deposit whose terms name the MTA, with one batch of `vials`
    vials, released after three passed checks unless `release` is false. Restrictions that
    need the lab's own permit get one first."""

    def make(
        taxon: Taxon = exempli,
        *,
        restrictions: Sequence[RestrictionInput] = (),
        risk_group: int = 1,
        vials: int = 5,
        purpose: Purpose = Purpose.DISTRIBUTION,
        release: bool = True,
        **terms_changes: Any,
    ) -> Strain:
        access = access_for(curator)
        for restriction in restrictions:
            kind = NEEDS_LAB_PERMIT.get(RestrictionKind(restriction.kind))
            if kind is not None and not lab.authorisations.filter(kind=kind).exists():
                make_permit(lab, kind)
        with as_actor(curator):
            deposit = deposits.deposit_receive(
                access=access,
                lab=lab,
                data=deposits.NewDeposit(
                    depositor=depositor,
                    received_on=date(2026, 10, 1),
                    condition=Condition.INTACT,
                    name_as_received=f"{taxon.name} D1",
                    terms=terms(**{"mta": mta, **terms_changes}),
                ),
            )
            deposit = deposits.deposit_start_check(access=access, deposit=deposit)
            deposit = deposits.deposit_accept(
                access=access,
                deposit=deposit,
                facts=facts(taxon, restrictions=list(restrictions), risk_group=risk_group),
            )
            assert deposit.strain is not None
            passage0 = Passage.objects.get(strain=deposit.strain, number=0)
            batch = preserve(curator, passage0, vial_count=vials, purpose=purpose)
            if release:
                pass_all(curator, batch)
                lineage.batch_release(access=access, batch=batch, reason="checks passed")
        return deposit.strain

    return make


@pytest.fixture
def make_requester(lab: Lab, curator: User) -> MakeRequester:
    def make(lab: Lab = lab, actor: User = curator, **changes: Any) -> Requester:
        with as_actor(actor):
            return services.requester_create(
                access=access_for(actor), lab=lab, data=requester_input(**changes)
            )

    return make


@pytest.fixture
def requester(make_requester: MakeRequester) -> Requester:
    return make_requester()


@pytest.fixture
def approver(lab: Lab) -> User:
    """A second manager: approves regulated requests in the tests of the two-person rule
    (#89), so the curator and the manager stay free to prepare and to confirm."""
    return member_of(lab, Role.MANAGER, "approver")


@pytest.fixture
def regulated(
    *, approver: User, curator: User, lab: Lab, requester: Requester, supply: Supply, mockia: Taxon
) -> Regulated:
    """A request for `quantity` vials of a dual-use strain (invented Mockia vulgaris, a manager
    finding only), approved by `by` (the approver) with a reason, and prepared by
    `prepared_by` when given. Each call makes a strain of its own unless `strain` is passed."""

    def make(
        quantity: int = 1,
        *,
        strain: Strain | None = None,
        prepared_by: User | None = None,
        by: User = approver,
    ) -> DistributionRequest:
        chosen = strain or supply(mockia, restrictions=[DUAL_USE], vials=6)
        request = submit(curator, lab, requester, [(chosen, quantity)])
        accept_mtas(curator, request)
        request = approve(by, request, "Dual-use inside the EU needs no licence.")
        if prepared_by is not None:
            request = prepare(prepared_by, request)
        return request

    return make


@pytest.fixture
def world(
    *,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mta: MtaTemplate,
    approver: User,
    regulated: Regulated,
    mockia: Taxon,
) -> dict[str, object]:
    """One of everything a service acts on, made by the curator through the services; the
    regulated requests approved and prepared by `approver`, so the curator may confirm."""
    strain = supply(vials=6)
    dual_use = supply(mockia, restrictions=[DUAL_USE], vials=6)
    awaiting = regulated(strain=dual_use, prepared_by=approver)
    permit = add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE)
    request = submit(curator, lab, requester, [(strain, 1)])
    accepted = submit(curator, lab, requester, [(strain, 1)])
    accept_mtas(curator, accepted)
    approved = submit(curator, lab, requester, [(strain, 1)])
    accept_mtas(curator, approved)
    approve(curator, approved)
    return {
        "lab": lab,
        "requester": requester,
        "strain": strain,
        "permit": permit,
        "request": request,
        "accepted": accepted,
        "approved": approved,
        "mta": mta,
        "regulated_approved": regulated(strain=dual_use),
        "awaiting": awaiting,
        "awaiting_preparation": awaiting.preparations.get().public_id,
    }

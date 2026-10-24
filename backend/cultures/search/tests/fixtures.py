"""Fixtures of the search tests: one of each kind in a lab and in another lab, all made through
the services. Helpers: support.py."""

from dataclasses import dataclass
from datetime import date

import pytest

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.deposits import services as deposits
from cultures.deposits.models import Condition, Deposit, Depositor
from cultures.deposits.tests.support import DUAL_USE, JANA, as_actor, facts, terms
from cultures.distribution.models import DistributionRequest, Requester
from cultures.distribution.tests.support import Supply, submit
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.lineage import services as lineage
from cultures.lineage.models import Passage, Vial
from cultures.lineage.tests.support import preserve, vials_of
from cultures.storage.models import StorageUnit, UnitKind
from cultures.storage.tests.conftest import MakeUnit, Tree
from cultures.strains.models import Strain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User


def intake(
    lab: Lab,
    curator: User,
    depositor: Depositor,
    name: str,
    taxon: Taxon | None = None,
    **strain_facts: object,
) -> Deposit:
    """A deposit as received, or accepted as a strain when a taxon is given."""
    access = access_for(curator)
    with as_actor(curator):
        deposit = deposits.deposit_receive(
            access=access,
            lab=lab,
            data=deposits.NewDeposit(
                depositor=depositor,
                received_on=date(2026, 10, 1),
                condition=Condition.INTACT,
                name_as_received=name,
                terms=terms(),
            ),
        )
        if taxon is not None:
            deposit = deposits.deposit_start_check(access=access, deposit=deposit)
            deposit = deposits.deposit_accept(
                access=access, deposit=deposit, facts=facts(taxon, **strain_facts)
            )
    return deposit


def batch_of(
    curator: User, strain: Strain, count: int, box: StorageUnit | None = None
) -> list[Vial]:
    with as_actor(curator):
        batch = preserve(
            curator, Passage.objects.get(strain=strain, number=0), vial_count=count, box=box
        )
    return vials_of(batch)


def label(barcode: str, vial: Vial, actor: User) -> Vial:
    with audit_context(channel=Channel.API, actor=actor, request_id="req-setup"):
        return lineage.vial_set_barcode(access=access_for(actor), vial=vial, barcode=barcode)


@dataclass
class Stock:
    """In `lab` (MYC): a strain with two vials in Box 1 (one with barcode TUBE-1), a regulated
    strain with a vial in a box nothing else is in (barcode TUBE-R), a deposit still received, and
    a request. In `other_lab` (BAC): a strain from a deposit with a vial of the same barcode
    TUBE-1, and a deposit still received. The names start with "Testella" or "Mockia"."""

    strain: Strain
    vials: list[Vial]
    regulated: Strain
    masked: Vial
    secret_box: StorageUnit
    received: Deposit
    request: DistributionRequest
    other_strain: Strain
    other_vial: Vial
    other_received: Deposit
    other_curator: User


@pytest.fixture
def stock(
    *,
    lab: Lab,
    other_lab: Lab,
    curator: User,
    depositor: Depositor,
    exempli: Taxon,
    mockia: Taxon,
    tree: Tree,
    make_unit: MakeUnit,
    supply: Supply,
    requester: Requester,
) -> Stock:
    strain = intake(lab, curator, depositor, "Testella exempli S1", exempli).strain
    assert strain is not None
    vials = batch_of(curator, strain, 2, tree.box)
    label("TUBE-1", vials[0], curator)
    regulated = intake(
        lab, curator, depositor, "Mockia vulgaris R1", mockia, restrictions=[DUAL_USE]
    ).strain
    assert regulated is not None
    secret_box = make_unit(UnitKind.BOX, "Box Hidden", tree.rack, slot=2)
    masked = batch_of(curator, regulated, 1, secret_box)[0]
    label("TUBE-R", masked, curator)
    received = intake(lab, curator, depositor, "Testella exempli Q7")
    request = submit(curator, lab, requester, [(supply(), 1)])

    other_curator = member_of(other_lab, Role.CURATOR, "other-curator")
    with as_actor(other_curator):
        other_depositor = deposits.depositor_create(
            access=access_for(other_curator), lab=other_lab, contact=JANA, institution=""
        )
    other_strain = intake(other_lab, other_curator, other_depositor, "Testella exempli B1", exempli)
    assert other_strain.strain is not None
    other_vial = label("TUBE-1", batch_of(other_curator, other_strain.strain, 1)[0], other_curator)
    other_received = intake(other_lab, other_curator, other_depositor, "Testella exempli Q8")
    return Stock(
        strain=strain,
        vials=vials,
        regulated=regulated,
        masked=masked,
        secret_box=secret_box,
        received=received,
        request=request,
        other_strain=other_strain.strain,
        other_vial=other_vial,
        other_received=other_received,
        other_curator=other_curator,
    )

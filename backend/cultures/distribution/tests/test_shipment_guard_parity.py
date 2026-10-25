"""The shipment trigger restates two Python rules by hand (ADR 0010, #125): which strain is
regulated (regulating_restrictions()) and which package facts a confirmation repeats from its
preparation (PACKAGE_FIELDS). These tests are built from the Python side, so a change there
that the trigger does not follow fails here, in either direction."""

from decimal import Decimal
from typing import Any

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from cultures.biosafety.models import RestrictionKind
from cultures.deposits.models import Contact
from cultures.distribution.models import (
    PACKAGE_FIELDS,
    ClassificationBasis,
    Coolant,
    DistributionRequest,
    PackingInstruction,
    Shipment,
    ShipmentPreparation,
    TransportClass,
)
from cultures.strains.models import Strain, StrainRestriction
from cultures.strains.selectors import regulating_restrictions
from cultures.strains.tests.conftest import end_restriction
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import Regulated, Supply, accept_mtas, approve, open_preparation, submit
from .test_two_person import confirmation_row

pytestmark = pytest.mark.django_db

ONE_STEP_REFUSED = "a regulated strain leaves only with a confirmed preparation"
NOT_AS_PREPARED = "a confirmed shipment is what was prepared"


class Kept(Exception):
    """Rolls back a savepoint whose insert the table accepted."""


def refused_by_the_table(message: str, insert: Any) -> bool:
    """True when the insert fails with the trigger's message, False when the table takes it
    (then the row is rolled back). Any other refusal is a broken test, not an answer."""
    try:
        with transaction.atomic():
            insert()
            raise Kept
    except Kept:
        return False
    except IntegrityError as error:
        assert message in str(error), error
        return True


# Regulated: every case regulating_restrictions() tells apart, plus cases it might be widened to.

REFERENCES = {
    RestrictionKind.CZ_VRAT: ("Příloha 1, bod 2", "", None),
    RestrictionKind.CZ_RAT: ("Příloha 2, bod 9", "", None),
    RestrictionKind.DUAL_USE: ("1C351.c", "(EU) 2025/2003", None),
    RestrictionKind.QUARANTINE_PEST: ("Annex II, Part B", "", None),
    RestrictionKind.GMO: ("MŽP notification 2026/12", "", 1),
}
CASES = [
    ("no restriction", 1, None, False),
    ("no restriction, risk group 3", 3, None, False),
    *[(f"active {kind.value}", 1, kind, False) for kind in RestrictionKind],
    ("an ended cz_rat", 1, RestrictionKind.CZ_RAT, True),
]


def test_the_cases_cover_every_restriction_kind() -> None:
    assert set(REFERENCES) == set(RestrictionKind)
    assert {kind for _, _, kind, ended in CASES if kind and not ended} == set(RestrictionKind)


def restrict(strain: Strain, kind: RestrictionKind) -> StrainRestriction:
    """A restriction row as the table holds it. The service's own gates (a lab permit for some
    kinds) are Python rules of another kind and not what the shipment trigger reads."""
    reference, act, gmo_category = REFERENCES[kind]
    return StrainRestriction.objects.create(
        lab=strain.lab,
        strain=strain,
        kind=kind,
        reference=reference,
        act=act,
        gmo_category=gmo_category,
    )


def one_step_shipment(request: DistributionRequest, shipper: User) -> Shipment:
    contact = Contact.objects.create(lab=request.lab, name="Jan Odpovědný", phone="+420 555 000")
    return Shipment.objects.create(
        lab=request.lab,
        request=request,
        transport_class=TransportClass.NOT_SUBJECT,
        classification_basis=ClassificationBasis.EXEMPT_NON_PATHOGENIC,
        classified_by=shipper,
        classified_at=timezone.now(),
        packing_instruction=PackingInstruction.TRIPLE,
        responsible=contact,
        carrier="Example Courier",
        shipped_by=shipper,
        shipped_at=timezone.now(),
    )


@pytest.mark.parametrize(
    ("case", "risk_group", "kind", "ended"), CASES, ids=[case for case, *_ in CASES]
)
def test_the_table_refuses_a_one_step_shipment_exactly_when_python_calls_the_strain_regulated(
    *,
    case: str,
    risk_group: int,
    kind: RestrictionKind | None,
    ended: bool,
    curator: User,
    manager: User,
    lab: Any,
    requester: Any,
    supply: Supply,
    exempli: Taxon,
) -> None:
    # Approved while unrestricted, so no gate of the approval stands in the way; the trigger
    # reads the restrictions at the moment the shipment row is written.
    strain = supply(exempli)
    request = submit(curator, lab, requester, [(strain, 1)])
    accept_mtas(curator, request)
    request = approve(manager, request, "Approved for the parity test.")
    Strain.objects.filter(pk=strain.pk).update(risk_group=risk_group)
    if kind is not None:
        restriction = restrict(strain, kind)
        if ended:
            end_restriction(restriction, proposer=curator, confirmer=manager)
    regulated = regulating_restrictions().filter(strain=strain).exists()
    refused = refused_by_the_table(ONE_STEP_REFUSED, lambda: one_step_shipment(request, manager))
    assert refused == regulated, f"{case}: Python regulated={regulated}, table refused={refused}"


# Package facts: every field of PACKAGE_FIELDS, changed alone, makes a confirmation refused.


def different(field: str, prepared: ShipmentPreparation) -> Any:
    """A value of `field` other than the preparation's, of the right type."""
    current = getattr(prepared, field)
    choices = {
        "transport_class": TransportClass.values,
        "classification_basis": ClassificationBasis.values,
        "packing_instruction": PackingInstruction.values,
        "coolant": Coolant.values,
    }
    if field in choices:
        return next(value for value in choices[field] if value != current)
    if field == "coolant_kg":
        return (current or Decimal(0)) + Decimal("1.5")
    if field == "responsible":
        return Contact.objects.create(lab=prepared.lab, name="Eva Jiná", phone="+420 555 111")
    return f"{current} changed"


def test_different_knows_every_package_field(*, curator: User, regulated: Regulated) -> None:
    prepared = open_preparation(regulated(prepared_by=curator))
    for field in PACKAGE_FIELDS:
        assert different(field, prepared) != getattr(prepared, field), field


@pytest.mark.parametrize("field", PACKAGE_FIELDS)
def test_the_table_refuses_a_confirmation_that_changes_any_package_field(
    *, field: str, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)
    preparation = open_preparation(request)
    changed = {field: different(field, preparation)}
    assert refused_by_the_table(
        NOT_AS_PREPARED,
        lambda: confirmation_row(request, preparation, shipped_by=manager, **changed),
    ), f"the shipment trigger does not compare {field}"


def test_an_unchanged_confirmation_is_taken(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    """The control: the same row without a change passes the trigger, so a refusal above is
    the changed field, not the row."""
    request = regulated(prepared_by=curator)
    preparation = open_preparation(request)
    assert not refused_by_the_table(
        NOT_AS_PREPARED, lambda: confirmation_row(request, preparation, shipped_by=manager)
    )

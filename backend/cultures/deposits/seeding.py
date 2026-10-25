"""What seed_dev and seed_e2e make of deposits, through the deposit services: depositors, MTA
versions and deposits in each intake state, the accepted ones making their strains.

Found again by natural keys, so a second run creates nothing twice: a depositor by its lab and
contact name, MTA versions by their lab and code (the versions a code has are the first ones
listed, the rest are published in order), a deposit by its lab and name as received. A deposit
found is never moved on. Taxa, MTA versions and depositors are found by name when they are used,
after the deposit was not found.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.strains.models import Strain
from cultures.strains.seeding import SeedFacts
from cultures.taxonomy import seeding as seed_taxa

from . import services
from .models import AbsScope, Condition, Decision, Deposit, Depositor, MtaTemplate, Use

State = Literal["received", "checking", "rejected", "accepted"]


@dataclass(frozen=True)
class SeedMta:
    title: str
    text: str


@dataclass(frozen=True)
class SeedTerms:
    abs_scope: AbsScope
    uses: Sequence[tuple[Use, Decision]]
    mta: tuple[str, int] | None = None  # code and version
    country_of_origin: str = ""
    collection_date: str = ""
    pic_reference: str = ""
    mat_reference: str = ""
    permit_reference: str = ""


@dataclass(frozen=True)
class SeedDeposit:
    name_as_received: str
    depositor: str  # the depositor's contact name
    received_on: date
    condition: Condition
    terms: SeedTerms
    state: State
    condition_note: str = ""
    depositor_passages: int | None = None
    rejection_reason: str = ""  # rejected
    strain: SeedFacts | None = None  # accepted: what the check found


def depositor(access: Access, lab: Lab, contact: services.ContactInput, institution: str) -> None:
    if not Depositor.objects.filter(lab=lab, contact__name=contact.name).exists():
        services.depositor_create(access=access, lab=lab, contact=contact, institution=institution)


def mta_versions(access: Access, lab: Lab, code: str, versions: Sequence[SeedMta]) -> None:
    published = MtaTemplate.objects.filter(lab=lab, code=code).count()
    for version in versions[published:]:
        services.mta_template_publish(
            access=access, lab=lab, code=code, title=version.title, text=version.text
        )


def deposit(access: Access, lab: Lab, data: SeedDeposit) -> tuple[Deposit, bool]:
    """The deposit, received by `access` and moved to its state; True when this run made it."""
    found = Deposit.objects.filter(lab=lab, name_as_received=data.name_as_received).first()
    if found is not None:
        return found, False
    terms = data.terms
    made = services.deposit_receive(
        access=access,
        lab=lab,
        data=services.NewDeposit(
            depositor=Depositor.objects.get(lab=lab, contact__name=data.depositor),
            received_on=data.received_on,
            condition=data.condition,
            condition_note=data.condition_note,
            name_as_received=data.name_as_received,
            depositor_passages=data.depositor_passages,
            terms=services.TermsInput(
                abs_scope=terms.abs_scope,
                uses=list(terms.uses),
                mta=MtaTemplate.objects.get(lab=lab, code=terms.mta[0], version=terms.mta[1])
                if terms.mta
                else None,
                country_of_origin=terms.country_of_origin,
                collection_date=terms.collection_date,
                pic_reference=terms.pic_reference,
                mat_reference=terms.mat_reference,
                permit_reference=terms.permit_reference,
            ),
        ),
    )
    if data.state == "received":
        return made, True
    made = services.deposit_start_check(access=access, deposit=made)
    if data.state == "rejected":
        services.deposit_reject(access=access, deposit=made, reason=data.rejection_reason)
    if data.state != "accepted":
        return made, True
    facts = data.strain
    assert facts is not None  # noqa: S101 (an accepted deposit names its strain)
    made = services.deposit_accept(
        access=access,
        deposit=made,
        facts=services.StrainFacts(
            taxon=seed_taxa.named(facts.taxon),
            identified_on=facts.identified_on,
            identification_method=facts.identification_method,
            risk_group=facts.risk_group,
            animal_pathogenicity=facts.animal_pathogenicity,
            plant_pathogenicity=facts.plant_pathogenicity,
            isolation_source=facts.isolation_source,
            country_of_origin=facts.country_of_origin,
            isolation_date=facts.isolation_date,
            restrictions=list(facts.restrictions),
        ),
    )
    return made, True


def accepted_strain(lab: Lab, name_as_received: str) -> Strain:
    """The strain an accepted deposit of the lab made."""
    strain = Deposit.objects.get(lab=lab, name_as_received=name_as_received).strain
    assert strain is not None  # noqa: S101 (the seed names accepted deposits only)
    return strain

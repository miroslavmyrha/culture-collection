"""What seed_dev makes of strains, through the strain services: strains entered with the
curator's role, each followed by its history (reclassified, risk group changed, a restriction
added, or ended by two people: the curator proposes, the lab's manager confirms, #105).

Strains are never deleted, so a strain is found again by its lab and name as received, and one
found is never changed: a second run changes nothing. The facts of a strain are also what a
deposit's acceptance needs (deposits.seeding).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from cultures.growth import seeding as seed_growth
from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.taxonomy import seeding as seed_taxa

from . import services
from .models import Pathogenicity, Strain, StrainRestriction


@dataclass(frozen=True)
class SeedFacts:
    """What identifies and classes a strain. The taxon is found by its name when it is used."""

    taxon: str
    identified_on: date
    identification_method: str
    risk_group: int
    animal_pathogenicity: Pathogenicity = Pathogenicity.UNKNOWN
    plant_pathogenicity: Pathogenicity = Pathogenicity.UNKNOWN
    isolation_source: str = ""
    country_of_origin: str = ""
    isolation_date: str = ""
    restrictions: Sequence[services.RestrictionInput] = field(default_factory=tuple)


@dataclass(frozen=True)
class Reclassify:
    taxon: str
    identified_on: date
    method: str
    reason: str


@dataclass(frozen=True)
class SetRiskGroup:
    risk_group: int
    reason: str


@dataclass(frozen=True)
class AddRestriction:
    restriction: services.RestrictionInput
    reason: str


@dataclass(frozen=True)
class EndRestriction:
    """Ends the open restriction of this kind and reference."""

    kind: str
    reference: str
    reason: str


@dataclass(frozen=True)
class SetGrowth:
    """How the strain is grown, from the lab's list of media."""

    growth: seed_growth.SeedGrowth
    reason: str


Step = Reclassify | SetRiskGroup | AddRestriction | EndRestriction | SetGrowth


@dataclass(frozen=True)
class SeedStrain:
    name_as_received: str
    facts: SeedFacts
    history: Sequence[Step] = field(default_factory=tuple)


def strain(curator: Access, manager: Access, lab: Lab, data: SeedStrain) -> bool:
    """The strain with its history, entered by `curator`; `manager` confirms the end of a
    restriction. True when created."""
    if Strain.objects.filter(lab=lab, name_as_received=data.name_as_received).exists():
        return False
    facts = data.facts
    made = services.strain_create(
        access=curator,
        lab=lab,
        data=services.NewStrain(
            name_as_received=data.name_as_received,
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
    for step in data.history:
        made = _step(curator, manager, made, step)
    return True


def set_growth(curator: Access, strain: Strain, step: SetGrowth) -> Strain:
    """The strain's growth conditions, set by `curator`. The same conditions again change
    nothing, so a deposit's strain can be given its conditions on every run."""
    return services.strain_set_growth(
        access=curator,
        strain=strain,
        growth=seed_growth.growth(strain.lab, step.growth),
        reason=step.reason,
    )


def _step(curator: Access, manager: Access, strain: Strain, step: Step) -> Strain:
    match step:
        case SetGrowth():
            return set_growth(curator, strain, step)
        case Reclassify():
            return services.strain_reclassify(
                access=curator,
                strain=strain,
                taxon=seed_taxa.named(step.taxon),
                identified_on=step.identified_on,
                method=step.method,
                reason=step.reason,
            )
        case SetRiskGroup():
            return services.strain_set_risk_group(
                access=curator, strain=strain, risk_group=step.risk_group, reason=step.reason
            )
        case AddRestriction():
            services.strain_restriction_add(
                access=curator, strain=strain, restriction=step.restriction, reason=step.reason
            )
            return strain
        case EndRestriction():
            row = StrainRestriction.objects.get(
                strain=strain, kind=step.kind, reference=step.reference, ended_at=None
            )
            proposal = services.strain_restriction_end_propose(
                access=curator, restriction=row, reason=step.reason
            )
            services.strain_restriction_end_confirm(
                access=manager, restriction=row, proposal=proposal.public_id
            )
            return strain

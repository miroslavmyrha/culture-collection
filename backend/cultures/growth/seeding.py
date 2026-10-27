"""What seed_dev makes of growth, through the growth services: the lab's list of media and the
conditions a strain or a passage is grown under.

A medium is found by its lab and name in any case, and is never changed again: a second run
creates nothing twice. A medium with a retire reason is retired once, by the run that finds it
active.
"""

from dataclasses import dataclass

from cultures.labs.access import Access
from cultures.labs.models import Lab

from . import services
from .models import GrowthMedium


@dataclass(frozen=True)
class SeedMedium:
    name: str
    composition_reference: str = ""
    retire_reason: str = ""  # retired right after it is made, with this reason


@dataclass(frozen=True)
class SeedGrowth:
    """Conditions as the seed files state them: the medium by name, in the strain's lab."""

    medium: str | None = None
    temperature_low_c: int | None = None
    temperature_high_c: int | None = None
    atmosphere: str = ""


def medium(curator: Access, lab: Lab, data: SeedMedium) -> bool:
    """The medium of the lab, made by `curator`. True when created."""
    found = GrowthMedium.objects.filter(lab=lab, name__iexact=data.name).first()
    created = found is None
    if found is None:
        found = services.medium_create(
            access=curator,
            lab=lab,
            name=data.name,
            composition_reference=data.composition_reference,
        )
    if created and data.retire_reason:
        services.medium_retire(access=curator, medium=found, reason=data.retire_reason)
    return created


def growth(lab: Lab, data: SeedGrowth) -> services.Growth:
    """The conditions as the services take them. The medium must be in the lab's list."""
    return services.Growth(
        medium=GrowthMedium.objects.get(lab=lab, name__iexact=data.medium) if data.medium else None,
        temperature_low_c=data.temperature_low_c,
        temperature_high_c=data.temperature_high_c,
        atmosphere=data.atmosphere,
    )

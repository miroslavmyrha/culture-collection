"""What seed_dev makes of biosafety, through the services: the permits a lab holds.

A permit is found again by its lab, kind and reference, so a second run adds none twice. One the
data ends is ended once, by the run that finds it still open.
"""

from dataclasses import dataclass
from datetime import date

from cultures.labs.models import Lab

from . import services
from .models import AuthorisationKind, LabAuthorisation


@dataclass(frozen=True)
class SeedAuthorisation:
    kind: AuthorisationKind
    permit_reference: str  # contains /DEV/ or "(invented example)"
    valid_from: date
    expires_on: date | None = None  # the last valid day
    ended_on: date | None = None  # the first invalid day
    end_reason: str = ""


def authorisation(lab: Lab, data: SeedAuthorisation) -> LabAuthorisation:
    found = LabAuthorisation.objects.filter(
        lab=lab, kind=data.kind, permit_reference=data.permit_reference
    ).first()
    if found is None:
        found = services.authorisation_create(
            lab=lab,
            kind=data.kind,
            permit_reference=data.permit_reference,
            valid_from=data.valid_from,
            expires_on=data.expires_on,
        )
    if data.ended_on is not None and found.ended_on is None:
        services.authorisation_end(
            authorisation=found, ended_on=data.ended_on, reason=data.end_reason
        )
    return found

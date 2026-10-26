"""Helpers of the biosafety tests: permits built with only the fields that matter."""

from datetime import date
from typing import Any

from model_bakery import baker

from cultures.biosafety.models import ISSUER_OF, AuthorisationKind, LabAuthorisation
from cultures.labs.models import Lab


def make_permit(
    lab: Lab, kind: AuthorisationKind = AuthorisationKind.CZ_VRAT, **fields: Any
) -> LabAuthorisation:
    values: dict[str, Any] = {
        "lab": lab,
        "kind": kind,
        "issuer": ISSUER_OF[kind],
        "permit_reference": "SÚJB/2026/001",
        "valid_from": date(2026, 1, 1),
        "expires_on": date(2026, 12, 31),
        **fields,
    }
    permit: LabAuthorisation = baker.make(LabAuthorisation, **values)
    return permit

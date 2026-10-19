"""A lab, staff acting outside a request, and permits built with only the fields that matter."""

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from model_bakery import baker

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import Channel
from cultures.biosafety.models import ISSUER_OF, AuthorisationKind, LabAuthorisation
from cultures.labs.models import Lab
from cultures.users.models import User


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


@pytest.fixture
def lab() -> Lab:
    found: Lab = baker.make(Lab, name="Mycology", code="MYC")
    return found


@pytest.fixture
def other_lab() -> Lab:
    found: Lab = baker.make(Lab, name="Bacteriology", code="BAC")
    return found


@pytest.fixture
def staff() -> User:
    user: User = baker.make(User, username="staff", is_staff=True, is_superuser=True)
    return user


@pytest.fixture
def as_staff(staff: User) -> Iterator[AuditContext]:
    with audit_context(channel=Channel.COMMAND, actor=staff, request_id="cmd-1") as context:
        yield context

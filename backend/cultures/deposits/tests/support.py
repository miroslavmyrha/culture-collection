"""Data and helpers for the deposits tests. Fixtures: fixtures.py, imported by conftest.py.

Contacts are invented people at example.org. Taxa are the strains tests' invented ones.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import Channel
from cultures.deposits.models import AbsScope, Decision, Deposit, Depositor, Use
from cultures.deposits.services import ContactInput, StrainFacts, TermsInput
from cultures.strains.tests.conftest import DUAL_USE, GMO, LAB_ID, QUARANTINE, VRAT, make_permit
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

__all__ = ["DUAL_USE", "GMO", "QUARANTINE", "VRAT", "ContactInput", "make_permit"]

LAB_URL = f"/api/v1/labs/{LAB_ID}"
DEPOSITS_URL = f"{LAB_URL}/deposits/"
DEPOSITORS_URL = f"{LAB_URL}/depositors/"
MTA_URL = f"{LAB_URL}/mta-templates/"

ALL_PERMITTED: tuple[tuple[Use, Decision], ...] = tuple(
    (Use(use), Decision.PERMIT) for use in Use.values
)
JANA = ContactInput("Jana Vzorová", "jana.vzorova@example.org", "Vzorová 1\n602 00 Brno")


def terms(**changes: Any) -> TermsInput:
    values: dict[str, Any] = {"abs_scope": AbsScope.NOT_IN_SCOPE, "uses": ALL_PERMITTED, **changes}
    return TermsInput(**values)


def terms_body(**changes: Any) -> dict[str, Any]:
    """Terms as the API takes them."""
    return {
        "mta": None,
        "abs_scope": "not_in_scope",
        "uses": [{"use": use, "decision": "permit"} for use in Use.values],
        **changes,
    }


def facts(taxon: Taxon, **changes: Any) -> StrainFacts:
    values: dict[str, Any] = {
        "taxon": taxon,
        "identified_on": date(2026, 1, 10),
        "identification_method": "16S rRNA gene sequence",
        "risk_group": 1,
        **changes,
    }
    return StrainFacts(**values)


def facts_body(taxon: Taxon, **changes: Any) -> dict[str, Any]:
    return {
        "taxon": str(taxon.public_id),
        "identified_on": "2026-01-10",
        "identification_method": "16S rRNA gene sequence",
        "risk_group": 1,
        **changes,
    }


def as_actor(actor: User) -> AbstractContextManager[AuditContext]:
    return audit_context(channel=Channel.API, actor=actor, request_id="req-setup")


MakeDepositor = Callable[..., Depositor]
MakeDeposit = Callable[..., Deposit]

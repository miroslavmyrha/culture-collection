"""People, labs, taxa and strains for the strains tests, named after what they are.

- lab: Mycology (MYC), fixed public id, one member of every role.
- other_lab: Bacteriology (BAC), managed by `outsider`: the highest role, elsewhere.
- Taxa: Bacillus > B. subtilis > subsp. spizizenii, Vibrio subtilis a synonym of
  B. subtilis, Escherichia > E. coli on another branch.
"""

from collections.abc import Callable, Iterator
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from django.contrib.auth.models import update_last_login
from django.contrib.auth.signals import user_logged_in

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import Channel

# The production roles inside the test transaction, the same fixtures the audit tests use.
from cultures.audit.tests.conftest import database_roles, runtime_role  # noqa: F401
from cultures.biosafety.models import (
    ISSUER_OF,
    AuthorisationKind,
    LabAuthorisation,
    RestrictionKind,
)
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import make_lab, member_of
from cultures.strains import services
from cultures.strains.models import Strain
from cultures.strains.services import NewStrain, RestrictionInput
from cultures.taxonomy.models import Rank, Taxon
from cultures.taxonomy.tests.conftest import make_synonym, make_taxon
from cultures.users.models import User

LAB_ID = UUID("00000000-0000-4000-8000-00000000000a")
STRAINS_URL = f"/api/v1/labs/{LAB_ID}/strains/"


@pytest.fixture(autouse=True)
def _no_last_login_update() -> Iterator[None]:
    """Logging in writes users.last_login: keep the history about our writes."""
    user_logged_in.disconnect(dispatch_uid="update_last_login")
    yield
    user_logged_in.connect(update_last_login, dispatch_uid="update_last_login")


@pytest.fixture
def lab() -> Lab:
    return make_lab(public_id=LAB_ID, name="Mycology", code="MYC")


@pytest.fixture
def other_lab() -> Lab:
    return make_lab(name="Bacteriology", code="BAC")


@pytest.fixture
def viewer(lab: Lab) -> User:
    return member_of(lab, Role.VIEWER, "viewer")


@pytest.fixture
def technician(lab: Lab) -> User:
    return member_of(lab, Role.TECHNICIAN, "technician")


@pytest.fixture
def curator(lab: Lab) -> User:
    return member_of(lab, Role.CURATOR, "curator")


@pytest.fixture
def manager(lab: Lab) -> User:
    return member_of(lab, Role.MANAGER, "manager")


@pytest.fixture
def outsider(other_lab: Lab) -> User:
    return member_of(other_lab, Role.MANAGER, "outsider")


@pytest.fixture
def team(viewer: User, technician: User, curator: User, manager: User) -> dict[Role, User]:
    return {
        Role.VIEWER: viewer,
        Role.TECHNICIAN: technician,
        Role.CURATOR: curator,
        Role.MANAGER: manager,
    }


@pytest.fixture
def bacillus() -> Taxon:
    return make_taxon("Bacillus", Rank.GENUS, authority="Cohn 1872")


@pytest.fixture
def subtilis(bacillus: Taxon) -> Taxon:
    return make_taxon(
        "Bacillus subtilis", Rank.SPECIES, bacillus, authority="(Ehrenberg 1835) Cohn 1872"
    )


@pytest.fixture
def spizizenii(subtilis: Taxon) -> Taxon:
    return make_taxon("Bacillus subtilis subsp. spizizenii", Rank.SUBSPECIES, subtilis)


@pytest.fixture
def vibrio_subtilis(subtilis: Taxon) -> Taxon:
    return make_synonym("Vibrio subtilis", Rank.SPECIES, subtilis)


@pytest.fixture
def coli() -> Taxon:
    return make_taxon("Escherichia coli", Rank.SPECIES, make_taxon("Escherichia", Rank.GENUS))


def new_strain(taxon: Taxon, **changes: Any) -> NewStrain:
    values: dict[str, Any] = {
        "name_as_received": "Bacillus subtilis 168",
        "taxon": taxon,
        "identified_on": date(2026, 1, 10),
        "identification_method": "16S rRNA gene sequence",
        "risk_group": 1,
        **changes,
    }
    return NewStrain(**values)


VRAT = RestrictionInput(RestrictionKind.CZ_VRAT, "Příloha 1, bod 2")
QUARANTINE = RestrictionInput(RestrictionKind.QUARANTINE_PEST, "Annex II, Part B")
DUAL_USE = RestrictionInput(RestrictionKind.DUAL_USE, "1C351.c", act="(EU) 2025/2003")
GMO = RestrictionInput(RestrictionKind.GMO, "MŽP notification 2026/12", gmo_category=1)


@pytest.fixture
def curator_access(curator: User) -> Access:
    return access_for(curator)


@pytest.fixture
def as_curator(curator: User) -> Iterator[AuditContext]:
    """Services run outside a request: the curator acting through the API channel."""
    with audit_context(channel=Channel.API, actor=curator, request_id="req-1") as context:
        yield context


MakeStrain = Callable[..., Strain]


@pytest.fixture
def make_strain(lab: Lab, curator: User, subtilis: Taxon) -> MakeStrain:
    """A strain accessioned by the curator through the service, in its own audit context."""

    def make(lab: Lab = lab, actor: User = curator, **changes: Any) -> Strain:
        data = new_strain(changes.pop("taxon", subtilis), **changes)
        with audit_context(channel=Channel.API, actor=actor, request_id="req-setup"):
            return services.strain_create(access=access_for(actor), lab=lab, data=data)

    return make


def make_permit(lab: Lab, kind: AuthorisationKind, **fields: Any) -> LabAuthorisation:
    values: dict[str, Any] = {
        "issuer": ISSUER_OF[kind],
        "permit_reference": f"{kind}-permit",
        "valid_from": date(2020, 1, 1),
        "expires_on": None,
        **fields,
    }
    return LabAuthorisation.objects.create(lab=lab, kind=kind, **values)

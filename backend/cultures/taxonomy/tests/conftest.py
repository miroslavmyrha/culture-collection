"""Taxa named after what they are, and staff acting outside a request.

The names are invented on purpose, so no test states a fact about a real organism. The
tree: Testella (genus) > Testella exempli (species) > Testella exempli subsp. alpha,
Fictivibrio exempli a synonym of Testella exempli, and Mockia vulgaris under Mockia, a
separate branch that no Testella filter may reach.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from model_bakery import baker

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import Channel
from cultures.taxonomy.models import Rank, Taxon, TaxonStatus
from cultures.users.models import User


def make_taxon(name: str, rank: Rank, parent: Taxon | None = None, **fields: Any) -> Taxon:
    taxon: Taxon = baker.make(
        Taxon, name=name, rank=rank, parent=parent, status=TaxonStatus.ACCEPTED, **fields
    )
    return taxon


def make_synonym(name: str, rank: Rank, accepted: Taxon) -> Taxon:
    taxon: Taxon = baker.make(
        Taxon, name=name, rank=rank, status=TaxonStatus.SYNONYM, accepted=accepted
    )
    return taxon


@pytest.fixture
def testella() -> Taxon:
    return make_taxon("Testella", Rank.GENUS, authority="Roe 1999")


@pytest.fixture
def exempli(testella: Taxon) -> Taxon:
    return make_taxon("Testella exempli", Rank.SPECIES, testella, authority="Doe 2001")


@pytest.fixture
def alpha(exempli: Taxon) -> Taxon:
    return make_taxon("Testella exempli subsp. alpha", Rank.SUBSPECIES, exempli)


@pytest.fixture
def fictivibrio(exempli: Taxon) -> Taxon:
    return make_synonym("Fictivibrio exempli", Rank.SPECIES, exempli)


@pytest.fixture
def mockia_genus() -> Taxon:
    return make_taxon("Mockia", Rank.GENUS)


@pytest.fixture
def mockia(mockia_genus: Taxon) -> Taxon:
    return make_taxon("Mockia vulgaris", Rank.SPECIES, mockia_genus)


@pytest.fixture
def staff() -> User:
    user: User = baker.make(User, username="staff", is_staff=True, is_superuser=True)
    return user


@pytest.fixture
def as_staff(staff: User) -> Iterator[AuditContext]:
    """Services run outside a request: staff in a command."""
    with audit_context(channel=Channel.COMMAND, actor=staff, request_id="cmd-1") as context:
        yield context

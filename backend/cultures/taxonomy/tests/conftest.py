"""Taxa named after what they are, and staff acting outside a request.

The tree: Bacillus (genus) > Bacillus subtilis (species) > B. subtilis subsp. spizizenii,
Vibrio subtilis a synonym of Bacillus subtilis (its basionym), and Escherichia coli under
Escherichia, a separate branch that no Bacillus filter may reach.
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
def escherichia() -> Taxon:
    return make_taxon("Escherichia", Rank.GENUS)


@pytest.fixture
def coli(escherichia: Taxon) -> Taxon:
    return make_taxon("Escherichia coli", Rank.SPECIES, escherichia)


@pytest.fixture
def staff() -> User:
    user: User = baker.make(User, username="staff", is_staff=True, is_superuser=True)
    return user


@pytest.fixture
def as_staff(staff: User) -> Iterator[AuditContext]:
    """Services run outside a request: staff in a command."""
    with audit_context(channel=Channel.COMMAND, actor=staff, request_id="cmd-1") as context:
        yield context

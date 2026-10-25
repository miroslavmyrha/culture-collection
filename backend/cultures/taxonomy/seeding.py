"""What seed_dev and seed_e2e make of taxa, through the services.

A taxon is found again by its name and rank, so a second run creates none twice. The two
commands find and keep taxa in different ways, and each keeps its own: seed_e2e matches the
exact name and never changes a taxon it finds (staff may have edited the seed's taxa), seed_dev
matches the name in any case and gives a taxon it finds the parent the data names when it has
none and is no synonym (seed_e2e creates its genera without one).
"""

from dataclasses import dataclass

from . import services
from .models import IdentifierSystem, Rank, Taxon


@dataclass(frozen=True)
class SeedTaxon:
    name: str
    authority: str
    rank: Rank
    parent: str | None = None  # the parent's name
    accepted: str | None = None  # the accepted name's name: the taxon is its synonym
    ncbi: str | None = None  # NCBI Taxonomy id


def _named(name: str | None) -> Taxon | None:
    return Taxon.objects.get(name=name) if name else None


def _create(data: SeedTaxon, parent: Taxon | None, accepted: Taxon | None) -> None:
    made = services.taxon_create(
        fields=services.TaxonFields(
            name=data.name,
            authority=data.authority,
            rank=data.rank,
            parent=parent,
            accepted=accepted,
        )
    )
    if data.ncbi:
        services.taxon_identifier_add(taxon=made, system=IdentifierSystem.NCBI, value=data.ncbi)


def taxon(data: SeedTaxon) -> bool:
    """seed_e2e: created when no taxon has this name and rank, never changed. True when created."""
    if Taxon.objects.filter(name=data.name, rank=data.rank).exists():
        return False
    _create(data, _named(data.parent), _named(data.accepted))
    return True


def taxon_filling_parent(data: SeedTaxon) -> bool:
    """seed_dev: created when no taxon has this name (in any case) and rank; one found keeps
    everything but gains the parent when it has none and is no synonym. True when created."""
    parent = _named(data.parent)
    accepted = _named(data.accepted)
    found = Taxon.objects.filter(name__iexact=data.name, rank=data.rank).first()
    if found is not None:
        if parent is not None and found.parent_id is None and found.accepted_id is None:
            services.taxon_update(
                taxon=found,
                fields=services.TaxonFields(
                    name=found.name, authority=found.authority, rank=data.rank, parent=parent
                ),
            )
        return False
    _create(data, parent, accepted)
    return True

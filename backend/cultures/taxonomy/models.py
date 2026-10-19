"""One global taxonomy, managed by staff, read by every lab (ADR 0008, D4).

A taxon has no lab. Accepted taxa form a tree through `parent`. A synonym
points at its accepted name through `accepted` and has no parent of its own:
the tree holds accepted names only, so "genus Bacillus" means the accepted
taxa under Bacillus plus the synonyms of each (selectors.taxon_and_below).
External ids (NCBI, LPSN, MycoBank) are optional rows, so a fungus or a newly
described species without one can be stored.

What crosses rows is checked by the services under a lock: a parent ranks
above its child, a synonym's accepted taxon is accepted itself, no cycle.
"""

from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Upper

from cultures.core.models import PublicModel

# Services map a violation of these to a field error, so the names are constants.
TAXON_UNIQUE = "taxonomy_taxon_name_authority_rank_uniq"
IDENTIFIER_UNIQUE = "taxonomy_taxonidentifier_system_value_uniq"
IDENTIFIER_ONE_PER_SYSTEM = "taxonomy_taxonidentifier_taxon_system_uniq"


class Rank(models.TextChoices):
    """Highest first. Variety and form are ranks of the botanical code (fungi)."""

    DOMAIN = "domain"
    KINGDOM = "kingdom"
    PHYLUM = "phylum"
    CLASS = "class"
    ORDER = "order"
    FAMILY = "family"
    GENUS = "genus"
    SPECIES = "species"
    SUBSPECIES = "subspecies"
    VARIETY = "variety"
    FORM = "form"


RANK_ORDER: dict[str, int] = {rank: depth for depth, rank in enumerate(Rank.values)}


class TaxonStatus(models.TextChoices):
    ACCEPTED = "accepted"
    SYNONYM = "synonym"


class IdentifierSystem(models.TextChoices):
    NCBI = "ncbi", "NCBI Taxonomy"
    LPSN = "lpsn", "LPSN"
    MYCOBANK = "mycobank", "MycoBank"


class Taxon(PublicModel):
    # The scientific name without its authority: "Bacillus subtilis".
    name = models.CharField(max_length=200)
    # The nomenclatural citation as published, "(Ehrenberg 1835) Cohn 1872". Part of the
    # name, not a record about a person (registry.ROW_AUDITED_TABLES keeps its values).
    authority = models.CharField(max_length=200, blank=True)
    rank = models.CharField(max_length=20, choices=Rank.choices)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    status = models.CharField(max_length=20, choices=TaxonStatus.choices)
    accepted = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="synonyms"
    )

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            # Homonyms differ by authority or rank. The same name twice is a mistake. One
            # expression only: django-migration-linter 6.0.0 reads the table name of an index
            # with two expressions wrongly and flags a new table's index as locking it.
            models.UniqueConstraint(Upper("name"), "authority", "rank", name=TAXON_UNIQUE),
            models.CheckConstraint(
                condition=Q(name__regex=r"^\S(.*\S)?$"), name="taxonomy_taxon_name_trimmed"
            ),
            models.CheckConstraint(
                condition=Q(rank__in=Rank.values), name="taxonomy_taxon_rank_valid"
            ),
            # accepted is set if and only if the taxon is a synonym. Also the status check:
            # no other status passes it.
            models.CheckConstraint(
                condition=Q(status=TaxonStatus.SYNONYM, accepted__isnull=False)
                | Q(status=TaxonStatus.ACCEPTED, accepted__isnull=True),
                name="taxonomy_taxon_accepted_iff_synonym",
            ),
            # The tree holds accepted names only.
            models.CheckConstraint(
                condition=~Q(status=TaxonStatus.SYNONYM) | Q(parent__isnull=True),
                name="taxonomy_taxon_synonym_has_no_parent",
            ),
            models.CheckConstraint(
                condition=~Q(parent=F("pk")) & ~Q(accepted=F("pk")),
                name="taxonomy_taxon_not_its_own_parent_or_accepted",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.authority}".strip()


class TaxonIdentifier(PublicModel):
    taxon = models.ForeignKey(
        Taxon, on_delete=models.PROTECT, related_name="identifiers", db_index=False
    )
    system = models.CharField(max_length=20, choices=IdentifierSystem.choices)
    value = models.CharField(max_length=50)

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(fields=["system", "value"], name=IDENTIFIER_UNIQUE),
            # One id per system: a taxon has one NCBI taxid, one LPSN record, one MycoBank number.
            # Leads with taxon, so it also serves the foreign key (db_index=False below).
            models.UniqueConstraint(fields=["taxon", "system"], name=IDENTIFIER_ONE_PER_SYSTEM),
            models.CheckConstraint(
                condition=Q(system__in=IdentifierSystem.values),
                name="taxonomy_taxonidentifier_system_valid",
            ),
            models.CheckConstraint(
                condition=Q(value__regex=r"^\S+$"), name="taxonomy_taxonidentifier_value_no_space"
            ),
            # NCBI Taxonomy ids are integers (taxid).
            models.CheckConstraint(
                condition=~Q(system=IdentifierSystem.NCBI) | Q(value__regex=r"^[0-9]+$"),
                name="taxonomy_taxonidentifier_ncbi_numeric",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.system}:{self.value}"

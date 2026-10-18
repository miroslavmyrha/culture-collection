"""Reads of the global taxonomy. Taxa have no lab, so these take no access object: every
signed-in user reads them (ADR 0008, D4: labs read taxa, staff change them)."""

from django.db.models import Case, IntegerField, QuerySet, Value, When
from django.db.models.expressions import RawSQL

from .models import Taxon, TaxonStatus

# The accepted taxa at and below a start taxon, then the synonyms of each. The start is
# resolved to its accepted name first, so filtering by a synonym means its accepted taxon.
# Ranks strictly fall along every parent edge (services.check_taxon), so the walk ends;
# the depth cap is a second line against a tree changed outside the services.
_AT_AND_BELOW = """
WITH RECURSIVE tree(id, depth) AS (
    SELECT COALESCE(accepted_id, id), 0 FROM taxonomy_taxon WHERE id = %s
    UNION ALL
    SELECT child.id, tree.depth + 1
      FROM taxonomy_taxon child JOIN tree ON child.parent_id = tree.id
     WHERE tree.depth < 32
)
SELECT id FROM tree
UNION
SELECT synonym.id FROM taxonomy_taxon synonym JOIN tree ON synonym.accepted_id = tree.id
"""


def taxon_and_below(taxon: Taxon) -> RawSQL:
    """A subquery of the ids of `taxon` (or its accepted name), every taxon under it, and
    their synonyms: `filter(taxon_id__in=taxon_and_below(t))` stays one query."""
    return RawSQL(_AT_AND_BELOW, [taxon.pk])  # noqa: S611 (a constant query, the pk is a parameter)


def taxon_list() -> QuerySet[Taxon]:
    """Every taxon by name, with what the API shows of it in the same query or one prefetch."""
    return (
        Taxon.objects.select_related("accepted", "parent")
        .prefetch_related("identifiers")
        .order_by("name", "authority", "pk")
    )


def taxon_search(taxa: QuerySet[Taxon], *, text: str) -> QuerySet[Taxon]:
    """Taxa whose name contains the text: names that start with it first, then by name."""
    text = " ".join(text.split())
    if not text:
        return taxa
    return (
        taxa.filter(name__icontains=text)
        .annotate(
            starts=Case(
                When(name__istartswith=text, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("starts", "name", "authority", "pk")
    )


def accepted_name(taxon: Taxon) -> Taxon:
    """The accepted taxon of a synonym, the taxon itself otherwise (caller selected `accepted`)."""
    if taxon.status == TaxonStatus.SYNONYM and taxon.accepted is not None:
        return taxon.accepted
    return taxon

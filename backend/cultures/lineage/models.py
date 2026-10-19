"""The lineage of a strain's material (ADR 0008, D1): deposit > passage > batch > vial.

A passage has exactly one source: the deposit (the material as received,
passage 0, D3) or a parent passage (a subculture, one more). A revived vial
becomes a third source with batches and vials (#16). Passages are never
changed or deleted: a guard trigger holds it (migration 0002). That a parent
belongs to the same strain crosses rows: the service that adds subcultures
checks it.
"""

from django.db import models
from django.db.models import F, Func, Q
from django.db.models.lookups import Exact

from cultures.core.models import PublicModel
from cultures.deposits.models import Deposit
from cultures.labs.models import Lab
from cultures.labs.querysets import LabScopedQuerySet
from cultures.strains.models import Strain


class Passage(PublicModel):
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+")
    strain = models.ForeignKey(Strain, on_delete=models.PROTECT, related_name="passages")
    # Counted from receipt: the material as received is 0 (ADR 0008, D3).
    number = models.PositiveIntegerField()
    source_deposit = models.OneToOneField(
        Deposit, on_delete=models.PROTECT, related_name="first_passage", null=True, blank=True
    )
    source_passage = models.ForeignKey(
        "self", on_delete=models.PROTECT, related_name="children", null=True, blank=True
    )

    objects = LabScopedQuerySet["Passage"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.CheckConstraint(
                condition=Exact(
                    Func(
                        F("source_deposit"),
                        F("source_passage"),
                        function="num_nonnulls",
                        output_field=models.IntegerField(),
                    ),
                    1,
                ),
                name="lineage_passage_one_source",
            ),
            models.CheckConstraint(
                condition=Q(source_deposit__isnull=False, number=0)
                | Q(source_deposit__isnull=True, number__gte=1),
                name="lineage_passage_zero_iff_from_deposit",
            ),
        ]

    def __str__(self) -> str:
        return f"passage {self.number} of {self.strain_id}"

"""How a strain is grown: the lab's list of media, and the growth conditions a strain and a
passage state (ADR 0008, amendment of 2026-10-27).

Sources. The OECD Best Practice Guidelines for Biological Resource Centres (2007) list growth
conditions in the minimum data set of a microbial strain (Microorganism domain, section 7,
Table 2), and the WFCC Guidelines for the Establishment and Operation of Collections of
Cultures of Microorganisms, 3rd edition (2010), section 11.1, put the growth medium and the
incubation temperature in the minimum record of a strain.

A medium is a row of the lab's list: a name, and where its recipe is written down (for example
a DSMZ medium number). Media are never deleted: one that is not used any more is retired, and
the strains and passages that named it keep it.

Conditions are four columns, the same on a strain and on a passage (`GrowthConditions`):
- the medium, from the lab's list;
- the temperature as a whole-degree range, low and high, equal for a single value. CCM prints
  "37 °C" or "25-37 °C", ATCC "37°C" or "37-40°C", and the range is what a catalogue says when
  one value is not enough;
- the atmosphere, the three values that DSMZ, CCM and ATCC print (`Atmosphere`).
Each may be unknown, which a blank column says. The database holds the ranges and the
vocabulary from the constants below.
"""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from cultures.core.models import PublicModel
from cultures.labs.models import Lab
from cultures.labs.querysets import LabScopedQuerySet

MEDIUM_NAME_UNIQUE = "growth_medium_lab_name_uniq"
TRIMMED = r"^\S(.*\S)?$"

# Whole degrees Celsius a culture is grown at: from 0 °C to 125 °C, which is above the hottest
# growth known, Methanopyrus kandleri strain 116 at 122 °C (Takai et al., PNAS 105, 2008).
MIN_GROWTH_TEMPERATURE_C = 0
MAX_GROWTH_TEMPERATURE_C = 125


class Atmosphere(models.TextChoices):
    """The gas phase a culture is grown under, as collections print it. DSMZ MediaDive lists
    "aerobic" and "anaerobic" beside the temperature of a strain on a medium; the CCM catalogue
    states "microaerophilic" in the cultivation line (CCM 3960, Campylobacter sputorum:
    "Medium 50, 37 °C, microaerophilic"); the ATCC product sheets state "Atmosphere:
    Anaerobic". A more specific gas mixture is a note on the medium, not a fourth value."""

    AEROBIC = "aerobic", "Aerobic"
    MICROAEROPHILIC = "microaerophilic", "Microaerophilic"
    ANAEROBIC = "anaerobic", "Anaerobic"


class GrowthMedium(PublicModel):
    """One medium of a lab's list. Retired for good when it is not used any more."""

    # No index of its own: the unique (lower(name), lab) below serves the lab's list.
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT, related_name="+", db_index=False)
    name = models.CharField(max_length=100)
    # Where the recipe is written down: "DSMZ medium 1", a catalogue page, a lab book page.
    composition_reference = models.CharField(max_length=200, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    objects = LabScopedQuerySet["GrowthMedium"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            # One expression first and lab second (django-migration-linter, see strains).
            models.UniqueConstraint(Lower("name"), "lab", name=MEDIUM_NAME_UNIQUE),
            models.CheckConstraint(
                condition=Q(name__regex=TRIMMED), name="growth_medium_name_trimmed"
            ),
            models.CheckConstraint(
                condition=Q(composition_reference="") | Q(composition_reference__regex=TRIMMED),
                name="growth_medium_composition_reference_trimmed",
            ),
        ]

    @property
    def is_retired(self) -> bool:
        return self.retired_at is not None

    def __str__(self) -> str:
        return self.name


def medium_index(name: str) -> models.Index:
    """Which rows of a table name a medium: the lookup a medium's screen and a retirement ask."""
    return models.Index(
        fields=["growth_medium"],
        name=name,
        condition=Q(growth_medium__isnull=False),
    )


def growth_constraints(table: str) -> list[models.CheckConstraint]:
    """The checks of the four condition columns, named for `table` ("strains_strain",
    "lineage_passage"). Each CHECK on a nullable column says isnull=False, or a null would pass
    it."""
    return [
        models.CheckConstraint(
            condition=Q(
                growth_temperature_low_c__isnull=True, growth_temperature_high_c__isnull=True
            )
            | Q(
                growth_temperature_low_c__isnull=False,
                growth_temperature_high_c__isnull=False,
                growth_temperature_low_c__gte=MIN_GROWTH_TEMPERATURE_C,
                growth_temperature_high_c__lte=MAX_GROWTH_TEMPERATURE_C,
                growth_temperature_low_c__lte=models.F("growth_temperature_high_c"),
            ),
            name=f"{table}_growth_temperature_range",
        ),
        models.CheckConstraint(
            condition=Q(growth_atmosphere="") | Q(growth_atmosphere__in=Atmosphere.values),
            name=f"{table}_growth_atmosphere_valid",
        ),
    ]


class GrowthConditions(models.Model):
    """The four columns of a strain's and a passage's growth conditions."""

    # The index is a partial one in Meta of each table, built concurrently by its own migration.
    growth_medium = models.ForeignKey(
        GrowthMedium,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
        db_index=False,
    )
    growth_temperature_low_c = models.SmallIntegerField(null=True, blank=True)
    growth_temperature_high_c = models.SmallIntegerField(null=True, blank=True)
    growth_atmosphere = models.CharField(
        max_length=20, choices=Atmosphere.choices, blank=True, default="", db_default=""
    )

    class Meta:
        abstract = True

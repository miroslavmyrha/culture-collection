"""Regulatory facts about agents and labs (ADR 0009). The app stores facts, nothing else.

RestrictionKind names the lists a strain can be on. A strain carries any
number of restrictions (strains.StrainRestriction). Two kinds may only be
held with a permit, recorded here as a LabAuthorisation of the lab:
- cz_vrat, a highly risky agent of decree 474/2002 Sb., Annex 1: a permit of
  SÚJB (act 281/2002 Sb., § 6);
- quarantine_pest, a Union quarantine pest of Implementing Regulation (EU)
  2019/2072, Annex II: a permit of ÚKZÚZ (act 326/2004 Sb., § 8).
Authorisations are never deleted. A permit that ends gets an end date and a
reason, so "which permit did the lab hold on that day" stays a query.
"""

from django.db import models
from django.db.models import F, Q

from cultures.core.models import PublicModel
from cultures.labs.models import Lab
from cultures.labs.querysets import LabScopedQuerySet

AUTHORISATION_UNIQUE = "biosafety_labauthorisation_lab_kind_reference_uniq"


class RestrictionKind(models.TextChoices):
    CZ_VRAT = "cz_vrat", "Highly risky agent (VRAT), decree 474/2002 Sb., Annex 1"
    CZ_RAT = "cz_rat", "Risky agent (RAT), decree 474/2002 Sb., Annex 2"
    DUAL_USE = "dual_use", "Dual-use item, Regulation (EU) 2021/821, Annex I"
    QUARANTINE_PEST = (
        "quarantine_pest",
        "Union quarantine pest, Regulation (EU) 2019/2072, Annex II",
    )
    GMO = "gmo", "Genetically modified organism in contained use, act 78/2004 Sb."


class AuthorisationKind(models.TextChoices):
    """The restriction kinds a lab may hold only with a permit (ADR 0009, Lab authorisation)."""

    CZ_VRAT = RestrictionKind.CZ_VRAT.value, "Permit to handle highly risky agents (VRAT)"
    QUARANTINE_PEST = RestrictionKind.QUARANTINE_PEST.value, "Permit to hold quarantine pests"


class Issuer(models.TextChoices):
    SUJB = "sujb", "SÚJB"
    UKZUZ = "ukzuz", "ÚKZÚZ"


# Who issues the permit for each kind: act 281/2002 Sb. § 6 (SÚJB), act 326/2004 Sb. § 8 (ÚKZÚZ).
ISSUER_OF: dict[AuthorisationKind, Issuer] = {
    AuthorisationKind.CZ_VRAT: Issuer.SUJB,
    AuthorisationKind.QUARANTINE_PEST: Issuer.UKZUZ,
}


class LabAuthorisation(PublicModel):
    # No index of its own: the unique constraint below leads with lab.
    lab = models.ForeignKey(
        Lab, on_delete=models.PROTECT, related_name="authorisations", db_index=False
    )
    kind = models.CharField(max_length=20, choices=AuthorisationKind.choices)
    issuer = models.CharField(max_length=10, choices=Issuer.choices)
    permit_reference = models.CharField(max_length=100)
    valid_from = models.DateField()
    # The last day of validity as the permit states it. Empty: the permit states none.
    expires_on = models.DateField(null=True, blank=True)
    # The day the permit stopped being valid before its expiry (revoked, surrendered, entered
    # in error), with the reason. The row stays.
    ended_on = models.DateField(null=True, blank=True)
    end_reason = models.TextField(blank=True)

    objects = LabScopedQuerySet["LabAuthorisation"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["lab", "kind", "permit_reference"], name=AUTHORISATION_UNIQUE
            ),
            # The kind and its issuer go together; no other kind passes.
            models.CheckConstraint(
                condition=Q(kind=AuthorisationKind.CZ_VRAT, issuer=Issuer.SUJB)
                | Q(kind=AuthorisationKind.QUARANTINE_PEST, issuer=Issuer.UKZUZ),
                name="biosafety_labauthorisation_kind_issuer",
            ),
            models.CheckConstraint(
                condition=Q(permit_reference__regex=r"^\S(.*\S)?$"),
                name="biosafety_labauthorisation_reference_trimmed",
            ),
            models.CheckConstraint(
                condition=Q(expires_on__isnull=True) | Q(expires_on__gte=F("valid_from")),
                name="biosafety_labauthorisation_expires_after_start",
            ),
            models.CheckConstraint(
                condition=Q(ended_on__isnull=True) | Q(ended_on__gte=F("valid_from")),
                name="biosafety_labauthorisation_ends_after_start",
            ),
            # An end date if and only if a reason.
            models.CheckConstraint(
                condition=Q(ended_on__isnull=True, end_reason="")
                | Q(ended_on__isnull=False, end_reason__regex=r"\S"),
                name="biosafety_labauthorisation_end_has_reason",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_issuer_display()} {self.permit_reference}"

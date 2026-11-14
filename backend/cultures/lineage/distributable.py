"""Which batches may go out: one definition, for the selectors of lineage, strains and
distribution and the seeds, in a module of its own so none of them imports another's selectors."""

from django.db.models import Q

from cultures.strains.models import StrainStatus

from .models import BatchStatus, Purpose

# A strain in these states may give material (deaccessioned and pending ones do not).
SUPPLYING = (StrainStatus.ACTIVE, StrainStatus.RESTRICTED)


def distributable(prefix: str = "") -> Q:
    """A batch whose vials may go out (ADR 0008, D15 and D16): released after its checks,
    distribution stock (seed stock never leaves), of a strain that still supplies. `prefix`
    reaches the batch from another model ("batch__" from a vial). The one definition: the
    batch figure and the vial selector of distribution (#18) both read it."""
    return Q(
        **{
            f"{prefix}status": BatchStatus.RELEASED,
            f"{prefix}purpose": Purpose.DISTRIBUTION,
            f"{prefix}strain__status__in": SUPPLYING,
        }
    )

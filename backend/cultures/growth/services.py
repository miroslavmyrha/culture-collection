"""Every write on the lab's list of growth media, and the checks of growth conditions that the
strain and passage services share (#79, ADR 0008 amendment of 2026-10-27).

Each service runs in audited_atomic() and records its event in the same transaction. Lock
order, as everywhere: the lab row first (labs.locks.lock_lab), then the rows of that lab. The
actor's role is read again under the lab lock. A medium is never deleted: it is retired, and
the strains and passages that name it keep it.
"""

from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Model
from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import MEDIUM_CHANGED, MEDIUM_CREATED, MEDIUM_RETIRED
from cultures.core.exceptions import Conflict, DomainError, Forbidden, NotFound
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Perm, Role, role_has

from .models import (
    MAX_GROWTH_TEMPERATURE_C,
    MEDIUM_NAME_UNIQUE,
    MIN_GROWTH_TEMPERATURE_C,
    Atmosphere,
    GrowthConditions,
    GrowthMedium,
)

MEDIUM = "medium"
MAX_NAME = 100
MAX_REFERENCE = 200


class InvalidGrowth(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class MediumNameTaken(DomainError):
    """A field error on the name: another medium of the lab has it (any case)."""

    default_code = "unique"
    default_detail = "The lab has a medium with this name."

    def __init__(
        self, detail: str | None = None, *, code: str | None = None, attr: str | None = "name"
    ) -> None:
        super().__init__(detail, code=code, attr=attr)


class MediumRetired(Conflict):
    default_code = "medium_retired"
    default_detail = "This medium is retired and changes no more."


@dataclass(frozen=True)
class Growth:
    """How something is grown. Every part may be unknown: no medium, no temperature (both
    ends None) and an empty atmosphere."""

    medium: GrowthMedium | None = None
    temperature_low_c: int | None = None
    temperature_high_c: int | None = None
    atmosphere: str = ""


def growth_of(obj: GrowthConditions) -> Growth:
    return Growth(
        medium=obj.growth_medium,
        temperature_low_c=obj.growth_temperature_low_c,
        temperature_high_c=obj.growth_temperature_high_c,
        atmosphere=obj.growth_atmosphere,
    )


def growth_values(growth: Growth) -> dict[str, Any]:
    """The conditions as an event records them: the medium by its public id."""
    return {
        "growth_medium": None if growth.medium is None else str(growth.medium.public_id),
        "growth_temperature_low_c": growth.temperature_low_c,
        "growth_temperature_high_c": growth.temperature_high_c,
        "growth_atmosphere": growth.atmosphere,
    }


def growth_fields(growth: Growth) -> dict[str, Any]:
    """The conditions as the model's keyword arguments."""
    return {
        "growth_medium": growth.medium,
        "growth_temperature_low_c": growth.temperature_low_c,
        "growth_temperature_high_c": growth.temperature_high_c,
        "growth_atmosphere": growth.atmosphere,
    }


def check_growth(growth: Growth) -> Growth:
    """The checks on the input alone, before any lock. A single temperature (no high end) is
    a range of one degree-value: high = low."""
    low, high = growth.temperature_low_c, growth.temperature_high_c
    if low is None and high is not None:
        raise InvalidGrowth("Enter the low end too.", attr="temperature_low_c")
    if low is not None:
        high = low if high is None else high
        for value, attr in ((low, "temperature_low_c"), (high, "temperature_high_c")):
            if not MIN_GROWTH_TEMPERATURE_C <= value <= MAX_GROWTH_TEMPERATURE_C:
                raise InvalidGrowth(
                    f"Use whole degrees from {MIN_GROWTH_TEMPERATURE_C} to "
                    f"{MAX_GROWTH_TEMPERATURE_C} °C.",
                    attr=attr,
                )
        if high < low:
            raise InvalidGrowth("The high end is below the low end.", attr="temperature_high_c")
    if growth.atmosphere and growth.atmosphere not in Atmosphere.values:
        raise InvalidGrowth("Choose an atmosphere from the list.", attr="atmosphere")
    return Growth(growth.medium, low, high, growth.atmosphere)


def locked_growth(growth: Growth, *, lab_id: int, current: Growth | None = None) -> Growth:
    """The growth with its medium read again under the lab lock (the caller holds it): a medium
    of another lab does not exist, and a retired one is not given to anything new, unless it is
    the medium `current` already has (a retired medium stays where it was used)."""
    growth = check_growth(growth)
    if growth.medium is None:
        return growth
    medium = GrowthMedium.objects.filter(pk=growth.medium.pk, lab_id=lab_id).first()
    if medium is None:
        raise InvalidGrowth("Choose a medium of this lab.", attr="medium")
    if medium.is_retired and (
        current is None or current.medium is None or current.medium.pk != medium.pk
    ):
        raise InvalidGrowth("This medium is retired: choose another.", attr="medium")
    return Growth(medium, growth.temperature_low_c, growth.temperature_high_c, growth.atmosphere)


def _require(access: Access, lab_id: int, perm: Perm) -> None:
    """The actor's role as committed now (caller holds the lab lock), not as the request began."""
    role = (
        Membership.objects.filter(lab_id=lab_id, user=access.user, user__is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    if role is None or not role_has(Role(role), perm):
        raise Forbidden


def _save(obj: Model) -> None:
    """The unique constraint is the final arbiter: a check before saving can race."""
    try:
        with transaction.atomic():
            obj.save()
    except IntegrityError as exc:
        diag = getattr(exc.__cause__, "diag", None)
        if str(getattr(diag, "constraint_name", "")) == MEDIUM_NAME_UNIQUE:
            raise MediumNameTaken from exc
        raise


def _clean(name: str, reference: str) -> tuple[str, str]:
    name = " ".join(name.split())
    reference = " ".join(reference.split())
    if not name:
        raise InvalidGrowth("Enter the name of the medium.", attr="name")
    if len(name) > MAX_NAME:
        raise InvalidGrowth(f"Use at most {MAX_NAME} characters.", attr="name")
    if len(reference) > MAX_REFERENCE:
        raise InvalidGrowth(
            f"Use at most {MAX_REFERENCE} characters.", attr="composition_reference"
        )
    return name, reference


def medium_create(
    *, access: Access, lab: Lab, name: str, composition_reference: str = ""
) -> GrowthMedium:
    name, reference = _clean(name, composition_reference)
    with audited_atomic():
        locked_lab = lock_lab(lab.pk)
        _require(access, locked_lab.pk, Perm.MANAGE_MEDIA)
        medium = GrowthMedium(lab=locked_lab, name=name, composition_reference=reference)
        _save(medium)
        record_event(
            MEDIUM_CREATED,
            Change(
                MEDIUM,
                medium.public_id,
                {"name": [None, name], "composition_reference": [None, reference]},
                lab_id=locked_lab.pk,
            ),
        )
    return medium


def _locked_medium(medium: GrowthMedium) -> GrowthMedium:
    locked = GrowthMedium.objects.select_for_update().filter(pk=medium.pk).first()
    if locked is None:
        raise NotFound
    return locked


def medium_update(
    *, access: Access, medium: GrowthMedium, name: str, composition_reference: str = ""
) -> GrowthMedium:
    """A new name or reference. Nothing changed records nothing. A retired medium changes no
    more."""
    name, reference = _clean(name, composition_reference)
    with audited_atomic():
        lock_lab(medium.lab_id)
        _require(access, medium.lab_id, Perm.MANAGE_MEDIA)
        locked = _locked_medium(medium)
        if locked.is_retired:
            raise MediumRetired
        changes: dict[str, list[Any]] = {}
        if locked.name != name:
            changes["name"] = [locked.name, name]
        if locked.composition_reference != reference:
            changes["composition_reference"] = [locked.composition_reference, reference]
        if not changes:
            return locked
        locked.name = name
        locked.composition_reference = reference
        _save(locked)
        record_event(
            MEDIUM_CHANGED,
            Change(MEDIUM, locked.public_id, changes, lab_id=locked.lab_id),
        )
    return locked


def medium_retire(*, access: Access, medium: GrowthMedium, reason: str) -> GrowthMedium:
    """For good, with a reason. Strains and passages that name it keep it; nothing new gets
    it. Retiring a retired medium changes nothing."""
    with audited_atomic():
        lock_lab(medium.lab_id)
        _require(access, medium.lab_id, Perm.MANAGE_MEDIA)
        locked = _locked_medium(medium)
        if locked.is_retired:
            return locked
        now = timezone.now()
        record_event(
            MEDIUM_RETIRED,
            Change(
                MEDIUM,
                locked.public_id,
                {"retired_at": [None, now.isoformat()]},
                lab_id=locked.lab_id,
            ),
            reason=reason,
        )
        locked.retired_at = now
        locked.save(update_fields=["retired_at", "updated_at"])
    return locked

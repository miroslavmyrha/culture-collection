"""Every write on strains: accession, reclassification, risk group and restrictions.

Each service runs in audited_atomic() and records one event that names the
strain (Change(strain_id=...), ADR 0008, D13). Lock order, as everywhere: the
lab row first (labs.locks.lock_lab), then the strain's rows. Under the lab
lock each service
- re-reads the actor's role in the lab, so a curator demoted after the request
  built its access object is refused (the members services do the same);
- checks the lab's permits for a cz_vrat or quarantine_pest restriction
  (biosafety.policy), so a permit ended at the same moment is seen;
- takes the next accession number from the lab's counter row, so two
  accessions never get the same number, also when they run at once.
A refusal raises before anything is written, or rolls back what was, so it
changes nothing and records nothing.

Rules (ADR 0009): a risk group 4 agent is refused, at accession and as a
change, and so is a group above the cap of a box holding the strain's vials.
A changed risk group, a reclassification, an added or an ended restriction
each need a reason (audit.registry, reason_required).
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Model
from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    STRAIN_CREATED,
    STRAIN_RECLASSIFIED,
    STRAIN_RESTRICTION_ADDED,
    STRAIN_RESTRICTION_ENDED,
    STRAIN_RISK_GROUP_CHANGED,
)
from cultures.biosafety.models import RestrictionKind
from cultures.biosafety.policy import permit_today, require_authorisation
from cultures.core.exceptions import Conflict, DomainError, Forbidden, NotFound, RuleViolation
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Perm, Role, role_has
from cultures.lineage.models import VialPlacement
from cultures.storage.models import StorageUnit
from cultures.taxonomy.models import Taxon

from .countries import COUNTRY_CODES
from .models import (
    ACCESSION_NUMBER_UNIQUE,
    ACCESSION_SEQ_UNIQUE,
    ACTIVE_RESTRICTION_UNIQUE,
    DUAL_USE_ENTRY,
    EU_ACT,
    PARTIAL_DATE,
    Pathogenicity,
    Strain,
    StrainCounter,
    StrainIdentification,
    StrainRestriction,
    StrainStatus,
)

STRAIN = "strain"
RISK_GROUP_REFUSED = 4
ACCESSION_REASON = "Identification at accession"
MAX_RESTRICTIONS = 10


class InvalidStrain(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class RiskGroupRefused(DomainError):
    """A field error on purpose: the form shows it on the risk group."""

    default_code = "risk_group_4_refused"
    default_detail = "The collection does not hold risk group 4 agents."

    def __init__(self, detail: str | None = None, *, attr: str | None = "risk_group") -> None:
        super().__init__(detail, attr=attr)


class RiskGroupAboveBoxCap(DomainError):
    """A field error on the risk group. Names no box: a regulated strain's place stays masked."""

    default_code = "risk_group_above_box_cap"
    default_detail = "A box holding this strain's vials does not allow this risk group."

    def __init__(self, detail: str | None = None, *, attr: str | None = "risk_group") -> None:
        super().__init__(detail, attr=attr)


class AccessionTaken(Conflict):
    default_code = "accession_taken"
    default_detail = "This accession number is taken: try again."


class RestrictionEnded(Conflict):
    default_code = "restriction_ended"
    default_detail = "This restriction has ended already."


@dataclass(frozen=True)
class RestrictionInput:
    kind: RestrictionKind
    reference: str
    act: str = ""
    gmo_category: int | None = None


@dataclass(frozen=True)
class NewStrain:
    name_as_received: str
    taxon: Taxon
    identified_on: date
    identification_method: str
    risk_group: int
    animal_pathogenicity: Pathogenicity = Pathogenicity.UNKNOWN
    plant_pathogenicity: Pathogenicity = Pathogenicity.UNKNOWN
    isolation_source: str = ""
    country_of_origin: str = ""
    isolation_date: str = ""
    restrictions: Sequence[RestrictionInput] = field(default_factory=tuple)


def normalised(text: str) -> str:
    """One space between words, NFC."""
    return " ".join(unicodedata.normalize("NFC", text).split())


# Checks on the input alone: no query, so they run before any lock.


def _check_risk_group(risk_group: int, attr: str = "risk_group") -> None:
    if risk_group == RISK_GROUP_REFUSED:
        raise RiskGroupRefused(attr=attr)
    if risk_group not in (1, 2, 3):
        raise InvalidStrain("A risk group is 1, 2 or 3.", attr=attr)


def _check_not_future(day: date, attr: str) -> None:
    if day > permit_today():
        raise InvalidStrain("This date is in the future.", attr=attr)


def check_partial_date(text: str, attr: str) -> None:
    """YYYY, YYYY-MM or YYYY-MM-DD, a real day, not after today."""
    if not text:
        return
    if not re.fullmatch(PARTIAL_DATE, text):
        raise InvalidStrain("Use YYYY, YYYY-MM or YYYY-MM-DD.", attr=attr)
    parts = [int(p) for p in text.split("-")]
    try:
        first = date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)  # noqa: PLR2004
    except ValueError:
        raise InvalidStrain("This day does not exist.", attr=attr) from None
    if first > permit_today():
        raise InvalidStrain("This date is in the future.", attr=attr)


def check_restriction(restriction: RestrictionInput, prefix: str = "") -> RestrictionInput:
    """The fields a kind needs, and only those. Returns it normalised."""
    reference = normalised(restriction.reference)
    act = normalised(restriction.act)
    if not reference:
        raise InvalidStrain("Enter the list entry.", attr=f"{prefix}reference")
    if restriction.kind == RestrictionKind.DUAL_USE:
        if not re.fullmatch(DUAL_USE_ENTRY, reference):
            raise InvalidStrain(
                "Enter an Annex I entry of 1C351, 1C353 or 1C354, for example 1C351.c.",
                attr=f"{prefix}reference",
            )
        if not re.fullmatch(EU_ACT, act):
            raise InvalidStrain(
                "Enter the act Annex I was read in, for example (EU) 2025/2003.",
                attr=f"{prefix}act",
            )
    elif act:
        raise InvalidStrain("Only a dual-use item names an act.", attr=f"{prefix}act")
    if restriction.kind == RestrictionKind.GMO:
        if restriction.gmo_category not in (1, 2, 3, 4):
            raise InvalidStrain("Choose the category, I to IV.", attr=f"{prefix}gmo_category")
    elif restriction.gmo_category is not None:
        raise InvalidStrain("Only a GMO has a category.", attr=f"{prefix}gmo_category")
    return RestrictionInput(restriction.kind, reference, act, restriction.gmo_category)


def _checked(data: NewStrain) -> NewStrain:
    name = normalised(data.name_as_received)
    if not name:
        raise InvalidStrain("Enter the name as received.", attr="name_as_received")
    method = normalised(data.identification_method)
    if not method:
        raise InvalidStrain("Enter how it was identified.", attr="identification_method")
    _check_risk_group(data.risk_group)
    _check_not_future(data.identified_on, "identified_on")
    if data.country_of_origin and data.country_of_origin not in COUNTRY_CODES:
        raise InvalidStrain("Choose a country.", attr="country_of_origin")
    check_partial_date(data.isolation_date, "isolation_date")
    if len(data.restrictions) > MAX_RESTRICTIONS:
        raise InvalidStrain(f"At most {MAX_RESTRICTIONS} restrictions.", attr="restrictions")
    restrictions = [
        check_restriction(r, prefix=f"restrictions.{i}.") for i, r in enumerate(data.restrictions)
    ]
    seen: set[tuple[str, str]] = set()
    for i, r in enumerate(restrictions):
        key = (r.kind, r.reference.upper())
        if key in seen:
            raise InvalidStrain(
                "This restriction is listed twice.", attr=f"restrictions.{i}.reference"
            )
        seen.add(key)
    return NewStrain(
        name_as_received=name,
        taxon=data.taxon,
        identified_on=data.identified_on,
        identification_method=method,
        risk_group=data.risk_group,
        animal_pathogenicity=data.animal_pathogenicity,
        plant_pathogenicity=data.plant_pathogenicity,
        isolation_source=normalised(data.isolation_source),
        country_of_origin=data.country_of_origin,
        isolation_date=data.isolation_date,
        restrictions=tuple(restrictions),
    )


def _check_reason(reason: str) -> str:
    """Before any write: the identification row and the event both need one."""
    if not reason.strip():
        raise RuleViolation("A reason is required.", code="reason_required", attr="reason")
    return reason.strip()


# Under the lab lock.


def _require_role(access: Access, lab_id: int) -> None:
    """The actor's role as committed now (caller holds the lab lock), not as the request began."""
    role = (
        Membership.objects.filter(lab_id=lab_id, user=access.user, user__is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    if role is None or not role_has(Role(role), Perm.MANAGE_STRAINS):
        raise Forbidden


def _next_seq(lab: Lab) -> int:
    """The lab's next accession sequence. Caller holds the lab lock; the counter row is locked
    too, so a writer that skipped the lab lock still waits here."""
    counter = StrainCounter.objects.select_for_update().filter(lab=lab).first()
    if counter is None:
        counter = StrainCounter.objects.create(lab=lab, last_seq=0)
    counter.last_seq += 1
    counter.save(update_fields=["last_seq"])
    return counter.last_seq


def _save(obj: Model, errors: dict[str, DomainError]) -> None:
    """The unique constraints are the final arbiter: a check before saving can race."""
    try:
        with transaction.atomic():
            obj.save()
    except IntegrityError as exc:
        diag = getattr(exc.__cause__, "diag", None)
        error = errors.get(str(getattr(diag, "constraint_name", "")))
        if error is not None:
            raise error from exc
        raise


def _restriction_values(r: StrainRestriction | RestrictionInput) -> dict[str, Any]:
    return {"kind": r.kind, "reference": r.reference, "act": r.act, "gmo_category": r.gmo_category}


def _locked_strain(strain: Strain) -> Strain:
    locked = Strain.objects.select_for_update().filter(pk=strain.pk).select_related("lab").first()
    if locked is None:
        raise NotFound
    return locked


def strain_create(*, access: Access, lab: Lab, data: NewStrain) -> Strain:
    """A curator's direct accession (ADR 0008, D8, until deposit intake exists): the strain
    is active at once and gets its number, "<lab code> <seq>", which never changes."""
    data = _checked(data)
    with audited_atomic():
        locked_lab = lock_lab(lab.pk)
        _require_role(access, locked_lab.pk)
        require_authorisation(
            lab_id=locked_lab.pk,
            kinds=[(r.kind, f"restrictions.{i}.kind") for i, r in enumerate(data.restrictions)],
        )
        seq = _next_seq(locked_lab)
        strain = Strain(
            lab=locked_lab,
            accession_number=f"{locked_lab.code} {seq}",
            accession_seq=seq,
            status=StrainStatus.ACTIVE,
            name_as_received=data.name_as_received,
            taxon=data.taxon,
            risk_group=data.risk_group,
            animal_pathogenicity=data.animal_pathogenicity,
            plant_pathogenicity=data.plant_pathogenicity,
            isolation_source=data.isolation_source,
            country_of_origin=data.country_of_origin,
            isolation_date=data.isolation_date,
        )
        taken = AccessionTaken()
        _save(strain, {ACCESSION_NUMBER_UNIQUE: taken, ACCESSION_SEQ_UNIQUE: taken})
        identification = StrainIdentification.objects.create(
            lab=locked_lab,
            strain=strain,
            taxon=data.taxon,
            identified_on=data.identified_on,
            method=data.identification_method,
            reason=ACCESSION_REASON,
            is_current=True,
        )
        for r in data.restrictions:
            StrainRestriction.objects.create(
                lab=locked_lab, strain=strain, **_restriction_values(r)
            )
        values: dict[str, Any] = {
            "accession_number": strain.accession_number,
            "status": strain.status,
            "name_as_received": strain.name_as_received,
            "taxon": str(data.taxon.public_id),
            "risk_group": strain.risk_group,
            "animal_pathogenicity": strain.animal_pathogenicity,
            "plant_pathogenicity": strain.plant_pathogenicity,
            "isolation_source": strain.isolation_source,
            "country_of_origin": strain.country_of_origin,
            "isolation_date": strain.isolation_date,
            "identification": {
                "public_id": str(identification.public_id),
                "identified_on": data.identified_on.isoformat(),
                "method": identification.method,
            },
            "restrictions": [_restriction_values(r) for r in data.restrictions],
        }
        record_event(
            STRAIN_CREATED,
            Change(
                STRAIN,
                strain.public_id,
                {k: [None, v] for k, v in values.items()},
                lab_id=locked_lab.pk,
                strain_id=strain.public_id,
            ),
        )
    return strain


def strain_reclassify(
    *, access: Access, strain: Strain, taxon: Taxon, identified_on: date, method: str, reason: str
) -> Strain:
    """A new identification becomes the current one; the history keeps the old ones."""
    method = normalised(method)
    if not method:
        raise InvalidStrain("Enter how it was identified.", attr="method")
    _check_not_future(identified_on, "identified_on")
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require_role(access, strain.lab_id)
        locked = _locked_strain(strain)
        current = (
            StrainIdentification.objects.select_for_update()
            .filter(strain=locked, is_current=True)
            .select_related("taxon")
            .get()
        )
        # Off first: the partial unique index allows one current row at any moment.
        current.is_current = False
        current.save(update_fields=["is_current", "updated_at"])
        added = StrainIdentification.objects.create(
            lab_id=locked.lab_id,
            strain=locked,
            taxon=taxon,
            identified_on=identified_on,
            method=method,
            reason=reason,
            is_current=True,
        )
        old_taxon = current.taxon
        locked.taxon = taxon
        locked.save(update_fields=["taxon", "updated_at"])
        record_event(
            STRAIN_RECLASSIFIED,
            Change(
                STRAIN,
                locked.public_id,
                {
                    "taxon": [str(old_taxon.public_id), str(taxon.public_id)],
                    "identification": [str(current.public_id), str(added.public_id)],
                    "identified_on": [None, identified_on.isoformat()],
                    "method": [None, method],
                },
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
    return locked


def _check_boxes_hold(strain: Strain, risk_group: int) -> None:
    """A higher group must fit the cap of every box that holds a vial of the strain now (ADR 0009,
    the may_store gate). Caller holds the lab lock, then the strain's row; the boxes are locked
    last, in pk order. Placements take the lab lock too, so none appears meanwhile."""
    boxes = list(
        StorageUnit.objects.select_for_update()
        .filter(
            pk__in=VialPlacement.objects.filter(
                removed_at__isnull=True, vial__batch__strain=strain
            ).values("box_id")
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    caps = StorageUnit.objects.filter(pk__in=boxes).with_path_facts()
    if any(vars(box)["effective_max_risk_group"] < risk_group for box in caps):
        raise RiskGroupAboveBoxCap


def strain_set_risk_group(
    *, access: Access, strain: Strain, risk_group: int, reason: str
) -> Strain:
    """The same group again changes nothing and records nothing. A higher group is refused while
    a box holding the strain's vials does not allow it; a lower one always fits."""
    _check_risk_group(risk_group)
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require_role(access, strain.lab_id)
        locked = _locked_strain(strain)
        if locked.risk_group == risk_group:
            return locked
        if risk_group > locked.risk_group:
            _check_boxes_hold(locked, risk_group)
        old = locked.risk_group
        locked.risk_group = risk_group
        record_event(
            STRAIN_RISK_GROUP_CHANGED,
            Change(
                STRAIN,
                locked.public_id,
                {"risk_group": [old, risk_group]},
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
        locked.save(update_fields=["risk_group", "updated_at"])
    return locked


def strain_restriction_add(
    *, access: Access, strain: Strain, restriction: RestrictionInput, reason: str
) -> StrainRestriction:
    restriction = check_restriction(restriction)
    with audited_atomic():
        lock_lab(strain.lab_id)
        _require_role(access, strain.lab_id)
        require_authorisation(lab_id=strain.lab_id, kinds=[(restriction.kind, "kind")])
        locked = _locked_strain(strain)
        added = StrainRestriction(
            lab_id=locked.lab_id, strain=locked, **_restriction_values(restriction)
        )
        _save(
            added,
            {
                ACTIVE_RESTRICTION_UNIQUE: InvalidStrain(
                    "The strain has this restriction already.", code="unique", attr="reference"
                )
            },
        )
        record_event(
            STRAIN_RESTRICTION_ADDED,
            Change(
                STRAIN,
                locked.public_id,
                {
                    "restriction": [
                        None,
                        {"public_id": str(added.public_id), **_restriction_values(added)},
                    ]
                },
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
    return added


def strain_restriction_end(
    *, access: Access, restriction: StrainRestriction, reason: str
) -> StrainRestriction:
    """The row stays, with the time it ended and why (an annex no longer lists the agent)."""
    with audited_atomic():
        lock_lab(restriction.lab_id)
        _require_role(access, restriction.lab_id)
        locked = (
            StrainRestriction.objects.select_for_update()
            .filter(pk=restriction.pk)
            .select_related("strain")
            .first()
        )
        if locked is None:
            raise NotFound
        if locked.ended_at is not None:
            raise RestrictionEnded
        locked.ended_at, locked.end_reason = timezone.now(), reason.strip()
        record_event(
            STRAIN_RESTRICTION_ENDED,
            Change(
                STRAIN,
                locked.strain.public_id,
                {
                    "restriction": [
                        {"public_id": str(locked.public_id), **_restriction_values(locked)},
                        None,
                    ]
                },
                lab_id=locked.lab_id,
                strain_id=locked.strain.public_id,
            ),
            reason=reason,
        )
        locked.save(update_fields=["ended_at", "end_reason", "updated_at"])
    return locked

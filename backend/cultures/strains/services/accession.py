"""A strain enters the collection and its identification changes: accession, with its number
from the lab's counter, reclassification and the growth conditions.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    STRAIN_CREATED,
    STRAIN_GROWTH_CHANGED,
    STRAIN_RECLASSIFIED,
)
from cultures.biosafety.models import RegulatoryListEntry
from cultures.biosafety.policy import require_authorisation
from cultures.core.constraints import save_arbitrated
from cultures.core.exceptions import Conflict
from cultures.growth.services import Growth, growth_fields, growth_of, growth_values, locked_growth
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab, require_committed
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.taxonomy.models import Taxon

from ..countries import COUNTRY_CODES
from ..models import (
    ACCESSION_NUMBER_UNIQUE,
    ACCESSION_SEQ_UNIQUE,
    Pathogenicity,
    Strain,
    StrainCounter,
    StrainIdentification,
    StrainRestriction,
    StrainStatus,
)
from ._shared import (
    ACCESSION_REASON,
    MAX_RESTRICTIONS,
    STRAIN,
    InvalidStrain,
    RestrictionInput,
    _check_basis,
    _check_basis_entry,
    _check_not_future,
    _check_reason,
    _check_risk_group,
    _entry_code,
    _entry_of,
    _locked_strain,
    _require_cz_agent,
    _restriction_values,
    check_partial_date,
    check_restriction,
    normalised,
)


class AccessionTaken(Conflict):
    default_code = "accession_taken"
    default_detail = "This accession number is taken: try again."


@dataclass(frozen=True)
class NewStrain:
    name_as_received: str
    taxon: Taxon
    identified_on: date
    identification_method: str
    risk_group: int
    # #169: what the risk group rests on, in words, and the list entry it was read in where it
    # was read in one. The words are always required: annex 7 of government order 361/2007 Sb.
    # says an agent it does not list is not thereby group 1, so no group follows from a list
    # alone (R-RISK-07).
    risk_group_basis: str
    risk_group_entry: RegulatoryListEntry | None = None
    animal_pathogenicity: Pathogenicity = Pathogenicity.UNKNOWN
    plant_pathogenicity: Pathogenicity = Pathogenicity.UNKNOWN
    isolation_source: str = ""
    country_of_origin: str = ""
    isolation_date: str = ""
    restrictions: Sequence[RestrictionInput] = field(default_factory=tuple)


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
        risk_group_basis=_check_basis(data.risk_group_basis, attr="risk_group_basis"),
        risk_group_entry=_check_basis_entry(
            data.risk_group_entry, data.risk_group, attr="risk_group_basis_entry"
        ),
        animal_pathogenicity=data.animal_pathogenicity,
        plant_pathogenicity=data.plant_pathogenicity,
        isolation_source=normalised(data.isolation_source),
        country_of_origin=data.country_of_origin,
        isolation_date=data.isolation_date,
        restrictions=tuple(restrictions),
    )


# Under the lab lock.


def _next_seq(lab: Lab) -> int:
    """The lab's next accession sequence. Caller holds the lab lock; the counter row is locked
    too, so a writer that skipped the lab lock still waits here."""
    counter = StrainCounter.objects.select_for_update().filter(lab=lab).first()
    if counter is None:
        counter = StrainCounter.objects.create(lab=lab, last_seq=0)
    counter.last_seq += 1
    counter.save(update_fields=["last_seq"])
    return counter.last_seq


def strain_create(*, access: Access, lab: Lab, data: NewStrain) -> Strain:
    """A curator's direct accession (ADR 0008, D8, until deposit intake exists): the strain
    is active at once and gets its number, "<lab code> <seq>", which never changes."""
    data = _checked(data)
    with audited_atomic():
        locked_lab = lock_lab(lab.pk)
        require_committed(access, locked_lab.pk, Perm.MANAGE_STRAINS)
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
            # #169: the accession states what the group rests on, like every change after it.
            risk_group_basis=data.risk_group_basis,
            risk_group_set_at=timezone.now(),
            risk_group_entry=data.risk_group_entry,
            animal_pathogenicity=data.animal_pathogenicity,
            plant_pathogenicity=data.plant_pathogenicity,
            isolation_source=data.isolation_source,
            country_of_origin=data.country_of_origin,
            isolation_date=data.isolation_date,
        )
        taken = AccessionTaken()
        save_arbitrated(strain, {ACCESSION_NUMBER_UNIQUE: taken, ACCESSION_SEQ_UNIQUE: taken})
        identification = StrainIdentification.objects.create(
            lab=locked_lab,
            strain=strain,
            taxon=data.taxon,
            identified_on=data.identified_on,
            method=data.identification_method,
            reason=ACCESSION_REASON,
            is_current=True,
        )
        entries = [_entry_of(r, f"restrictions.{i}.") for i, r in enumerate(data.restrictions)]
        _require_cz_agent(entries, {r.kind for r in data.restrictions}, prefix="restrictions.")
        for r, entry in zip(data.restrictions, entries, strict=True):
            StrainRestriction.objects.create(
                lab=locked_lab, strain=strain, list_entry=entry, **_restriction_values(r)
            )
        values: dict[str, Any] = {
            "accession_number": strain.accession_number,
            "status": strain.status,
            "name_as_received": strain.name_as_received,
            "taxon": str(data.taxon.public_id),
            "risk_group": strain.risk_group,
            "risk_group_basis": strain.risk_group_basis,
            "risk_group_entry": _entry_code(data.risk_group_entry),
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
        require_committed(access, strain.lab_id, Perm.MANAGE_STRAINS)
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


def strain_set_growth(*, access: Access, strain: Strain, growth: Growth, reason: str) -> Strain:
    """How the strain is grown (OECD BRC guidelines 2007, Microorganism domain, section 7;
    WFCC guidelines 2010, 11.1): the medium from the lab's list, the temperature as a range of
    whole degrees, the atmosphere. Replaces all four at once, each may be unknown. The same
    conditions again change nothing and record nothing. Passages already recorded keep the
    conditions they were grown under."""
    with audited_atomic():
        lock_lab(strain.lab_id)
        require_committed(access, strain.lab_id, Perm.MANAGE_STRAINS)
        locked = _locked_strain(strain)
        before = growth_of(locked)
        after = locked_growth(growth, lab_id=locked.lab_id, current=before)
        old, new = growth_values(before), growth_values(after)
        changes = {k: [old[k], new[k]] for k in new if old[k] != new[k]}
        if not changes:
            return locked
        for column, value in growth_fields(after).items():
            setattr(locked, column, value)
        record_event(
            STRAIN_GROWTH_CHANGED,
            Change(
                STRAIN,
                locked.public_id,
                changes,
                lab_id=locked.lab_id,
                strain_id=locked.public_id,
            ),
            reason=reason,
        )
        locked.save(update_fields=[*growth_fields(after), "updated_at"])
    return locked

"""Passages, and the batches preserved from them with their vials."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Max
from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_batch, record_event
from cultures.audit.registry import (
    BATCH_CREATED,
    PASSAGE_CREATED,
    VIAL_CREATED,
    VIAL_PLACED,
    VIALS_CREATED,
    VIALS_PLACED,
)
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import NotFound
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.storage.models import StorageUnit
from cultures.strains.models import Strain

from ..models import (
    BATCH_NUMBER_UNIQUE,
    MAX_VIALS_PER_BATCH,
    Batch,
    Method,
    Passage,
    Purpose,
    Vial,
    VialPlacement,
    VialStatus,
)
from ._shared import (
    BATCH,
    PASSAGE,
    VIAL,
    _check_may_store,
    _free_positions,
    _living_strain,
    _locked_box,
    _locked_vial,
    _ref,
    _require,
    _save,
    _transition,
    _where,
    normalised,
)
from .errors import (
    BatchNumberTaken,
    InvalidVial,
)


@dataclass(frozen=True)
class NewBatch:
    method: Method
    purpose: Purpose
    preserved_on: date
    vial_count: int
    cryoprotectant: str = ""
    # Place the new vials into this box, in fill order (row by row), or leave them unplaced.
    box: StorageUnit | None = None


# Passages.


def _new_passage(strain: Strain, number: int, **source: Any) -> Passage:
    passage = Passage.objects.create(lab_id=strain.lab_id, strain=strain, number=number, **source)
    values = {"number": number, **{k: _ref(v) for k, v in source.items()}}
    record_event(
        PASSAGE_CREATED,
        Change(
            PASSAGE,
            passage.public_id,
            {k: [None, v] for k, v in values.items()},
            lab_id=strain.lab_id,
            strain_id=strain.public_id,
        ),
    )
    return passage


def passage_subculture(*, access: Access, parent: Passage) -> Passage:
    """A subculture of a passage: the same strain, the parent's number plus one (D3)."""
    with audited_atomic():
        lock_lab(parent.lab_id)
        _require(access, parent.lab_id)
        fresh = Passage.objects.filter(pk=parent.pk).first()
        if fresh is None:
            raise NotFound
        strain = _living_strain(fresh.strain_id)
        return _new_passage(strain, fresh.number + 1, source_passage=fresh)


def vial_revive(*, access: Access, vial: Vial) -> Passage:
    """A vial is thawed or rehydrated and grown: it is consumed, and a passage starts from it,
    numbered one more than the passage its batch was preserved from."""
    with audited_atomic():
        lock_lab(vial.lab_id)
        _require(access, vial.lab_id)
        strain = _living_strain(vial.batch.strain_id)
        locked = _locked_vial(vial)
        number = Passage.objects.get(pk=locked.batch.passage_id).number + 1
        _transition(locked, VialStatus.CONSUMED, f"Revived as passage {number}.", access)
        return _new_passage(strain, number, source_vial=locked)


# Batches.


def _check_batch(data: NewBatch) -> NewBatch:
    if not 1 <= data.vial_count <= MAX_VIALS_PER_BATCH:
        raise InvalidVial(f"A batch has 1 to {MAX_VIALS_PER_BATCH} vials.", attr="vial_count")
    if data.preserved_on > permit_today():
        raise InvalidVial("This date is in the future.", attr="preserved_on")
    return NewBatch(
        method=data.method,
        purpose=data.purpose,
        preserved_on=data.preserved_on,
        vial_count=data.vial_count,
        cryoprotectant=normalised(data.cryoprotectant),
        box=data.box,
    )


def batch_preserve(*, access: Access, passage: Passage, data: NewBatch) -> Batch:
    """One preservation of one passage: the batch, its vials numbered from 1, and with a box
    the vials placed in its free positions in fill order. All or nothing: a box with fewer
    free positions than vials refuses the whole batch."""
    data = _check_batch(data)
    with audited_atomic():
        lock_lab(passage.lab_id)
        _require(access, passage.lab_id)
        strain = _living_strain(passage.strain_id)
        box = None
        if data.box is not None:
            box = _locked_box(data.box, passage.lab_id)
            _check_may_store(box, strain)
            free = _free_positions(box)
            if len(free) < data.vial_count:
                raise InvalidVial(
                    f"This box has {len(free)} free positions, the batch {data.vial_count} vials.",
                    code="box_full",
                    attr="box",
                )
        top = Batch.objects.filter(strain=strain).aggregate(top=Max("number"))["top"] or 0
        batch = Batch(
            lab_id=strain.lab_id,
            strain=strain,
            passage=passage,
            number=top + 1,
            method=data.method,
            cryoprotectant=data.cryoprotectant,
            preserved_on=data.preserved_on,
            vial_count_created=data.vial_count,
            purpose=data.purpose,
        )
        _save(batch, {BATCH_NUMBER_UNIQUE: BatchNumberTaken()})
        values: dict[str, Any] = {
            "number": batch.number,
            "passage": str(passage.public_id),
            "method": batch.method,
            "cryoprotectant": batch.cryoprotectant,
            "preserved_on": batch.preserved_on.isoformat(),
            "vial_count_created": batch.vial_count_created,
            "purpose": batch.purpose,
            "status": batch.status,
        }
        record_event(
            BATCH_CREATED,
            Change(
                BATCH,
                batch.public_id,
                {k: [None, v] for k, v in values.items()},
                lab_id=strain.lab_id,
                strain_id=strain.public_id,
            ),
        )
        vials = Vial.objects.bulk_create(
            Vial(lab_id=strain.lab_id, batch=batch, seq=seq)
            for seq in range(1, data.vial_count + 1)
        )
        record_batch(
            VIAL_CREATED,
            VIALS_CREATED,
            [
                Change(
                    VIAL,
                    vial.public_id,
                    {
                        "batch": [None, str(batch.public_id)],
                        "seq": [None, vial.seq],
                        "status": [None, vial.status],
                    },
                    lab_id=strain.lab_id,
                    strain_id=strain.public_id,
                )
                for vial in vials
            ],
        )
        if box is not None:
            _place_all(access, strain, box, vials, _free_positions(box))
    return batch


def _place_all(
    access: Access,
    strain: Strain,
    box: StorageUnit,
    vials: list[Vial],
    free: list[tuple[int, int]],
) -> None:
    now = timezone.now()
    placements = VialPlacement.objects.bulk_create(
        VialPlacement(
            lab_id=strain.lab_id,
            vial=vial,
            box=box,
            row=row,
            col=col,
            placed_at=now,
            placed_by=access.user,
        )
        for vial, (row, col) in zip(vials, free, strict=False)
    )
    record_batch(
        VIAL_PLACED,
        VIALS_PLACED,
        [
            Change(
                VIAL,
                placement.vial.public_id,
                {"location": [None, _where(placement)]},
                lab_id=strain.lab_id,
                strain_id=strain.public_id,
            )
            for placement in placements
        ],
    )

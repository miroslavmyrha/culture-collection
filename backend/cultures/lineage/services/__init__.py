"""Every write on passages, batches, vials and placements (#16, ADR 0008 amendment of
2026-10-19), the reveal of a regulated location (ADR 0009 amendment of the same day), the
checks of a batch with its release (#17, ADR 0008 amendment of 2026-10-20), the report of a
lost VRAT or RAT vial to the police (#159, ADR 0009 amendment of 2026-11-02), and the
destruction record (#160, ADR 0008 and ADR 0009 amendments of 2026-11-03).

Each service runs in audited_atomic() and records its events, each naming the strain
(Change(strain_id=...), D13). Lock order, as everywhere: the lab row first
(labs.locks.lock_lab), then the strain, then a destruction record, then the batch, then the
vial, then the box. Under the lab lock each service re-reads the actor's role (vials.handle:
technicians and up do the bench work; batches.release: curators and up release and hold), so a
member demoted after the request built its access object is refused, and reads the strain's
risk group, which changes only under the same lock. A refusal raises before anything is
written, or rolls back what was, so it changes nothing and records nothing.

The database holds the same rules on its own (migrations 0004, 0006, 0009, 0010 and 0014): the
vial's and the batch's edges, a release only after passed checks, the placement's box, lab and
bounds, one open placement per vial and per position, checks that are only added, a vial
destroyed only with its destruction record. The services check them first, so a person gets a
message, not a server error.
"""

from ..models import HELD
from ._shared import (
    BATCH,
    CHECK,
    LIVING,
    MANUAL_TARGETS,
    PASSAGE,
    VIAL,
    normalised,
)
from .checks import (
    VALUE_STEP,
    NewCheck,
    _move_batch,
    batch_hold,
    batch_release,
    check_enter_in_error,
    check_record,
    kinds_text,
    latest_checks,
    not_passed,
)
from .destructions import (
    NewDestruction,
    Required,
    destruction_confirm,
    destruction_enter_in_error,
    destruction_record,
    required_for,
)
from .errors import (
    AuthorisationMethodMissing,
    BatchEdgeNotAllowed,
    BatchExhausted,
    BatchNumberTaken,
    CheckEnteredInError,
    ChecksNotPassed,
    ConfirmOwnDestruction,
    DestructionEnteredInError,
    DestructionNeedsRecord,
    DestructionNotAwaiting,
    DestructionOutdated,
    EdgeNotAllowed,
    InvalidCheck,
    InvalidDestruction,
    InvalidVial,
    LossChanged,
    LossNotReportable,
    LossReported,
    MaterialDestroyed,
    PositionTaken,
    StrainNotActive,
    VialAlreadyPlaced,
    VialInDestruction,
    VialNotAvailable,
    VialNotInCollection,
    VialNotLost,
    VialNotToDestroy,
    VialPlacedMeanwhile,
    VialReserved,
)
from .locations import (
    Location,
    is_regulated,
    location_of,
    position_label,
    vial_reveal_location,
)
from .losses import vial_loss_report
from .passages import (
    NewBatch,
    batch_preserve,
    passage_subculture,
    vial_revive,
)
from .vials import (
    NewPlacement,
    batch_exhaust_if_emptied_locked,
    strain_vials_leave_locked,
    vial_place,
    vial_release_locked,
    vial_reserve_locked,
    vial_set_barcode,
    vial_ship_locked,
    vial_transition,
    vials_place,
)

__all__ = [
    "BATCH",
    "CHECK",
    "HELD",
    "LIVING",
    "MANUAL_TARGETS",
    "PASSAGE",
    "VALUE_STEP",
    "VIAL",
    "AuthorisationMethodMissing",
    "BatchEdgeNotAllowed",
    "BatchExhausted",
    "BatchNumberTaken",
    "CheckEnteredInError",
    "ChecksNotPassed",
    "ConfirmOwnDestruction",
    "DestructionEnteredInError",
    "DestructionNeedsRecord",
    "DestructionNotAwaiting",
    "DestructionOutdated",
    "EdgeNotAllowed",
    "InvalidCheck",
    "InvalidDestruction",
    "InvalidVial",
    "Location",
    "LossChanged",
    "LossNotReportable",
    "LossReported",
    "MaterialDestroyed",
    "NewBatch",
    "NewCheck",
    "NewDestruction",
    "NewPlacement",
    "PositionTaken",
    "Required",
    "StrainNotActive",
    "VialAlreadyPlaced",
    "VialInDestruction",
    "VialNotAvailable",
    "VialNotInCollection",
    "VialNotLost",
    "VialNotToDestroy",
    "VialPlacedMeanwhile",
    "VialReserved",
    "_move_batch",
    "batch_exhaust_if_emptied_locked",
    "batch_hold",
    "batch_preserve",
    "batch_release",
    "check_enter_in_error",
    "check_record",
    "destruction_confirm",
    "destruction_enter_in_error",
    "destruction_record",
    "is_regulated",
    "kinds_text",
    "latest_checks",
    "location_of",
    "normalised",
    "not_passed",
    "passage_subculture",
    "position_label",
    "required_for",
    "strain_vials_leave_locked",
    "vial_loss_report",
    "vial_place",
    "vial_release_locked",
    "vial_reserve_locked",
    "vial_reveal_location",
    "vial_revive",
    "vial_set_barcode",
    "vial_ship_locked",
    "vial_transition",
    "vials_place",
]

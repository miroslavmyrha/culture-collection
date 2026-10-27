"""Every write on passages, batches, vials and placements (#16, ADR 0008 amendment of
2026-10-19), the reveal of a regulated location (ADR 0009 amendment of the same day), and the
checks of a batch with its release (#17, ADR 0008 amendment of 2026-10-20).

Each service runs in audited_atomic() and records its events, each naming the strain
(Change(strain_id=...), D13). Lock order, as everywhere: the lab row first
(labs.locks.lock_lab), then the strain, then the batch, then the vial, then the box. Under
the lab lock each service re-reads the actor's role (vials.handle: technicians and up do the
bench work; batches.release: curators and up release and hold), so a member demoted after the
request built its access object is refused, and reads the strain's risk group, which changes
only under the same lock. A refusal raises before anything is written, or rolls back what
was, so it changes nothing and records nothing.

The database holds the same rules on its own (migrations 0004 and 0006): the vial's and the
batch's edges, a release only after passed checks, the placement's box, lab and bounds, one
open placement per vial and per position, checks that are only added. The services check
them first, so a person gets a message, not a server error.
"""

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
from .errors import (
    BatchEdgeNotAllowed,
    BatchExhausted,
    BatchNumberTaken,
    CheckEnteredInError,
    ChecksNotPassed,
    EdgeNotAllowed,
    InvalidCheck,
    InvalidVial,
    PositionTaken,
    StrainNotActive,
    VialNotAvailable,
    VialNotInCollection,
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
from .passages import (
    NewBatch,
    batch_preserve,
    passage_subculture,
    vial_revive,
)
from .vials import (
    HELD,
    batch_exhaust_if_emptied_locked,
    strain_vials_leave_locked,
    vial_place,
    vial_release_locked,
    vial_reserve_locked,
    vial_set_barcode,
    vial_ship_locked,
    vial_transition,
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
    "BatchEdgeNotAllowed",
    "BatchExhausted",
    "BatchNumberTaken",
    "CheckEnteredInError",
    "ChecksNotPassed",
    "EdgeNotAllowed",
    "InvalidCheck",
    "InvalidVial",
    "Location",
    "NewBatch",
    "NewCheck",
    "PositionTaken",
    "StrainNotActive",
    "VialNotAvailable",
    "VialNotInCollection",
    "VialPlacedMeanwhile",
    "VialReserved",
    "_move_batch",
    "batch_exhaust_if_emptied_locked",
    "batch_hold",
    "batch_preserve",
    "batch_release",
    "check_enter_in_error",
    "check_record",
    "is_regulated",
    "kinds_text",
    "latest_checks",
    "location_of",
    "normalised",
    "not_passed",
    "passage_subculture",
    "position_label",
    "strain_vials_leave_locked",
    "vial_place",
    "vial_release_locked",
    "vial_reserve_locked",
    "vial_reveal_location",
    "vial_revive",
    "vial_set_barcode",
    "vial_ship_locked",
    "vial_transition",
]

"""The refusals of the lineage services."""

from cultures.core.exceptions import Conflict, DomainError, Forbidden, RuleViolation


class InvalidVial(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class StrainNotActive(Conflict):
    default_code = "strain_not_active"
    default_detail = "The strain is not active: nothing is grown or preserved from it."


class PositionTaken(Conflict):
    default_code = "position_taken"
    default_detail = "Another vial is in this position."


class VialNotInCollection(Conflict):
    default_code = "vial_not_in_collection"
    default_detail = "This vial has left the collection or is lost: it has no place."


class VialAlreadyPlaced(Conflict):
    """Placing several vials (#77) takes vials in no box: a move is the vial's own place. The
    message names no box, the vial may be of a regulated strain (ADR 0009)."""

    default_code = "vial_already_placed"
    default_detail = "This vial is in a box already. Move it from its own row."


class VialPlacedMeanwhile(Conflict):
    default_code = "vial_placed_meanwhile"
    default_detail = "The vial was placed at the same moment: reload and try again."


class EdgeNotAllowed(DomainError):
    """A field error on the status."""

    default_code = "transition_not_allowed"

    def __init__(
        self, detail: str | None = None, *, code: str | None = None, attr: str | None = "status"
    ) -> None:
        super().__init__(detail, code=code, attr=attr)


class MaterialDestroyed(EdgeNotAllowed):
    """#150: the strain was deaccessioned with its material destroyed."""

    default_code = "strain_material_destroyed"
    default_detail = (
        "This strain was deaccessioned and its material destroyed: its vials are not used again."
        " Mark a found vial to destroy."
    )


class DestructionNeedsRecord(EdgeNotAllowed):
    """#160: a vial is destroyed only through a destruction record (services.destructions),
    never by a state change: for every strain, regulated or not."""

    default_code = "destruction_needs_record"
    default_detail = (
        "A vial is destroyed only with a destruction record: mark it to destroy, then record the"
        " destruction on the strain's Material tab."
    )


class BatchNumberTaken(Conflict):
    default_code = "batch_number_taken"
    default_detail = "Another batch took this number at the same moment: try again."


class VialReserved(Conflict):
    default_code = "vial_reserved"
    default_detail = (
        "This vial is reserved for a request. Cancel the request to free it, or ship it."
    )


class InvalidCheck(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class BatchExhausted(Conflict):
    default_code = "batch_exhausted"
    default_detail = "This batch is exhausted: it is not checked, released or held any more."


class BatchEdgeNotAllowed(Conflict):
    default_code = "transition_not_allowed"


class VialNotAvailable(Conflict):
    default_code = "vial_not_available"
    default_detail = "This vial is not available. Choose an available vial of the batch."


class CheckEnteredInError(Conflict):
    default_code = "check_entered_in_error"
    default_detail = "This check was entered in error already."


class ChecksNotPassed(RuleViolation):
    default_code = "checks_not_passed"


# The loss report (#159, act 281/2002 Sb., § 5(5)).


class VialNotLost(Conflict):
    """The vial was found (or never lost): there is no loss to report."""

    default_code = "vial_not_lost"
    default_detail = "This vial is not lost: it was found, so there is no loss to report."


class LossChanged(Conflict):
    """The vial was found and lost again since the caller read it: the report would be of
    another loss than the one the person saw."""

    default_code = "loss_changed"
    default_detail = "This vial was found and lost again since the page was loaded. Reload it."


class LossNotReportable(Conflict):
    default_code = "loss_not_reportable"
    default_detail = (
        "Its strain was not a highly risky or risky agent when the vial was lost: the act asks"
        " no report to the police."
    )


class LossReported(Conflict):
    default_code = "loss_reported"
    default_detail = "The report of this loss is recorded already."


# The destruction record (#160).


class InvalidDestruction(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class VialNotToDestroy(Conflict):
    default_code = "vial_not_to_destroy"
    default_detail = "This vial is not marked to destroy. Mark it to destroy first."


class VialInDestruction(Conflict):
    default_code = "vial_in_destruction"
    default_detail = "This vial is in a destruction record that waits for its confirmation already."


class DestructionNotAwaiting(Conflict):
    default_code = "destruction_not_awaiting"
    default_detail = (
        "This record does not wait for a confirmation: it was confirmed, entered in error, or"
        " needed none. Reload the page."
    )


class DestructionEnteredInError(Conflict):
    default_code = "destruction_entered_in_error"
    default_detail = "This record was entered in error already."


class DestructionOutdated(Conflict):
    """The strain's restrictions changed since the record: it no longer holds what they ask."""

    default_code = "destruction_outdated"
    default_detail = (
        "The strain's restrictions changed since the destruction was recorded, and the record no"
        " longer holds what they ask. Enter it in error and record the destruction again."
    )


class ConfirmOwnDestruction(Forbidden):
    """ADR 0009, decision Q2: a manager other than the recorder confirms."""

    default_code = "confirm_own_destruction"
    default_detail = "You recorded this destruction: a different manager confirms it."


class AuthorisationMethodMissing(RuleViolation):
    """Decision Q6: a quarantine pest is destroyed by the method its permit declares, and the
    collection holds no declared method for the permit."""

    default_code = "authorisation_method_missing"
    default_detail = (
        "The lab's ÚKZÚZ permit for quarantine pests has no destruction method recorded here."
        " Staff record the permit again with the method its application declared."
    )

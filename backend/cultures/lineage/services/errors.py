"""The refusals of the lineage services."""

from cultures.core.exceptions import Conflict, DomainError, RuleViolation


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

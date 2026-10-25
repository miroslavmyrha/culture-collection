"""The refusals of the distribution services."""

from cultures.core.exceptions import Conflict, DomainError, Forbidden, RuleViolation


class InvalidDistribution(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class WrongState(Conflict):
    """The request is not in the state the action starts from: someone acted first."""

    default_code = "request_state"
    default_detail = "The request is no longer in this state. Reload it."


class PermitEnded(Conflict):
    default_code = "permit_ended"
    default_detail = "This permit was ended already."


class ContactErased(Conflict):
    default_code = "contact_erased"
    default_detail = "This requester's contact was erased."


class NumberTaken(Conflict):
    default_code = "request_number_taken"
    default_detail = "Another request took this number at the same moment: try again."


class AcceptanceExists(Conflict):
    default_code = "acceptance_exists"
    default_detail = "An acceptance of this MTA version is recorded for this request already."


class RequestBlocked(RuleViolation):
    default_code = "request_blocked"


class DestinationRefused(RuleViolation):
    """Nothing leaves the EU (ADR 0009 amendment of 2026-10-20)."""


class ManagerRequired(Forbidden):
    default_code = "manager_approval_required"
    default_detail = "A finding on this request needs a manager's approval."


class NotEnoughVials(Conflict):
    default_code = "not_enough_vials"


class ReservedMeanwhile(Conflict):
    default_code = "vial_reserved_meanwhile"
    default_detail = "A vial was reserved at the same moment: try again."


class ShipmentBlocked(RuleViolation):
    default_code = "shipment_blocked"


class SecondPersonRequired(RuleViolation):
    """ADR 0009: a regulated line leaves only once a second person confirmed it. The code is the
    one #88 answered; since #89 the detail says how: prepare, then another person confirms."""

    default_code = "second_person_required"
    default_detail = (
        "A regulated strain is shipped only when a second person confirms it: prepare the"
        " shipment, and a different person confirms it."
    )


class ShipInOneStep(RuleViolation):
    """Only a request with a regulated line is prepared for a second person; the others ship."""

    default_code = "ship_in_one_step"
    default_detail = "No line of this request is regulated: ship it in one step."


class ConfirmOwnApproval(Forbidden):
    """ADR 0009: the person who approved the request does not confirm its shipment."""

    default_code = "confirm_own_approval"
    default_detail = "You approved this request: a different person confirms its shipment."


class ConfirmOwnPreparation(Forbidden):
    """ADR 0009: nobody confirms the shipment they prepared."""

    default_code = "confirm_own_preparation"
    default_detail = "You prepared this shipment: a different person confirms it."


class PreparationChanged(Conflict):
    """The confirmation names the preparation the confirmer read; another one is open now."""

    default_code = "preparation_changed"
    default_detail = "The prepared shipment changed meanwhile. Read it again before you confirm."


class PreparedMeanwhile(Conflict):
    default_code = "preparation_exists"
    default_detail = "Someone prepared this shipment at the same moment. Reload the request."

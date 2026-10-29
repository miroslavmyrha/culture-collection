"""Every write of distribution (#18, part A): requesters and their permits, requests with their
lines, MTA acceptances, the depositor's answers for a use on request (#144), and the decisions
on a request with the vials reserved at approval; the shipment of an approved request (#88), in
two steps by two people when a line is regulated (#89), with the documents it needs written in
the same transaction (#90).

Each service runs in audited_atomic() and records its events in the same transaction. Lock
order, as everywhere: the lab row first (labs.locks.lock_lab), then the request, then the
strains of its lines by pk, then their batches, then the vials (lineage keeps lab, strain,
batch, vial, box; a request sits between the lab and its strains). Under the lab lock each
service re-reads the actor's role, so a member demoted after the request built its access
object is refused. A refusal raises before anything is written, or rolls back what was, so it
changes nothing and records nothing.

Personal data (D11): the responsible scientist, an MTA's signer and a shipment's responsible
person are contacts; events record their fields as "changed", never the value. Events about a
line or its vials carry the strain (D13); a request spans strains, so its own events carry none
and each line has its own.
"""

from ._shared import (
    ACCEPTANCE,
    CONTACT,
    LINE,
    PERMIT,
    REQUEST,
    REQUESTER,
    SHIPMENT_DOCUMENT,
    SIGNATURES,
    _move,
    document_type,
    normalised,
)
from .answers import ANSWER_UNIQUE, depositor_answer_record
from .decisions import (
    request_approve,
    request_cancel,
    request_reject,
    requests_cancel_for_deaccession_locked,
)
from .errors import (
    AcceptanceExists,
    ConfirmOwnApproval,
    ConfirmOwnPreparation,
    ContactErased,
    DepositorAnswerExists,
    DestinationRefused,
    InvalidDistribution,
    ManagerRequired,
    NotEnoughVials,
    NumberTaken,
    PermitEnded,
    PreparationChanged,
    PreparedMeanwhile,
    RequestAwaitsConfirmation,
    RequestBlocked,
    ReservedMeanwhile,
    SecondPersonRequired,
    ShipInOneStep,
    ShipmentBlocked,
    WrongState,
)
from .inputs import (
    AcceptanceInput,
    ContactInput,
    DepositorAnswerInput,
    DocumentInput,
    LineInput,
    NewRequest,
    PermitInput,
    RequesterInput,
    ShipmentInput,
)
from .requesters import (
    permit_add,
    permit_end,
    requester_create,
    requester_update,
)
from .requests import (
    MAX_LINES,
    acceptance_record,
    request_submit,
)
from .shipment import (
    MAX_COOLANT_KG,
    PHONE,
    request_ship,
)
from .two_person import (
    request_confirm_shipment,
    request_prepare_shipment,
    request_withdraw_shipment,
)

__all__ = [
    "ACCEPTANCE",
    "ANSWER_UNIQUE",
    "CONTACT",
    "LINE",
    "MAX_COOLANT_KG",
    "MAX_LINES",
    "PERMIT",
    "PHONE",
    "REQUEST",
    "REQUESTER",
    "SHIPMENT_DOCUMENT",
    "SIGNATURES",
    "AcceptanceExists",
    "AcceptanceInput",
    "ConfirmOwnApproval",
    "ConfirmOwnPreparation",
    "ContactErased",
    "ContactInput",
    "DepositorAnswerExists",
    "DepositorAnswerInput",
    "DestinationRefused",
    "DocumentInput",
    "InvalidDistribution",
    "LineInput",
    "ManagerRequired",
    "NewRequest",
    "NotEnoughVials",
    "NumberTaken",
    "PermitEnded",
    "PermitInput",
    "PreparationChanged",
    "PreparedMeanwhile",
    "RequestAwaitsConfirmation",
    "RequestBlocked",
    "RequesterInput",
    "ReservedMeanwhile",
    "SecondPersonRequired",
    "ShipInOneStep",
    "ShipmentBlocked",
    "ShipmentInput",
    "WrongState",
    "_move",
    "acceptance_record",
    "depositor_answer_record",
    "document_type",
    "normalised",
    "permit_add",
    "permit_end",
    "request_approve",
    "request_cancel",
    "request_confirm_shipment",
    "request_prepare_shipment",
    "request_reject",
    "request_ship",
    "request_submit",
    "request_withdraw_shipment",
    "requester_create",
    "requester_update",
    "requests_cancel_for_deaccession_locked",
]

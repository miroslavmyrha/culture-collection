"""The input of the distribution services, as the API and the commands give it."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from cultures.deposits.models import Use
from cultures.strains.models import Strain

from ..models import (
    ClassificationBasis,
    Coolant,
    LegalForm,
    PackingInstruction,
    PermitKind,
    Requester,
    SignerRole,
    TransportClass,
)


@dataclass(frozen=True)
class ContactInput:
    name: str
    email: str = ""
    postal_address: str = ""
    phone: str = ""


@dataclass(frozen=True)
class RequesterInput:
    contact: ContactInput  # the responsible scientist; the postal address is the delivery address
    institution: str
    legal_form: LegalForm
    country: str
    lab_evidence: str
    lab_confirmed_on: date
    registration_number: str = ""
    seat: str = ""  # the registered office, as the business register gives it


@dataclass(frozen=True)
class DocumentInput:
    content: bytes


@dataclass(frozen=True)
class PermitInput:
    kind: PermitKind
    issuer: str
    issuer_country: str
    reference: str
    valid_from: date
    document: DocumentInput
    expires_on: date | None = None
    covers: str = ""
    quantity_allowed: int | None = None
    sendings_allowed: int | None = None
    endorsement_reference: str = ""
    endorsed_on: date | None = None
    gmo_category: int | None = None
    risk_group: int | None = None


@dataclass(frozen=True)
class LineInput:
    strain: Strain
    quantity: int


@dataclass(frozen=True)
class NewRequest:
    requester: Requester
    use: Use
    end_use: str
    containment_level: int
    lines: Sequence[LineInput]


@dataclass(frozen=True)
class AcceptanceInput:
    mta_id: int  # an MTA version pinned on a line of the request
    signer: ContactInput
    signer_role: SignerRole
    authorised_signatory: bool
    accepted_on: date
    document: DocumentInput


@dataclass(frozen=True)
class ShipmentInput:
    transport_class: TransportClass
    classification_basis: ClassificationBasis
    packing_instruction: PackingInstruction
    responsible: ContactInput  # name and phone of the person who answers for the package
    carrier: str
    basis_note: str = ""
    coolant: Coolant = Coolant.NONE
    coolant_kg: Decimal | None = None
    tracking_number: str = ""

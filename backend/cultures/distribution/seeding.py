"""What seed_dev and seed_e2e make of distribution, through the services: requesters with their
permits, and requests, each with the acceptance of its MTA versions where the data asks for it,
and approved where it asks for that (a request ready to ship, #88).

Found again by natural keys, so a second run changes nothing: a requester by its lab and
institution, a permit by its requester, kind and reference, a request by its lab and end use
(each seeded request has an end use of its own). Documents are a few bytes of an invented PDF.
"""

from dataclasses import dataclass, field
from datetime import date

from cultures.deposits.models import Use
from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.strains.models import Strain

from . import services
from .models import (
    DistributionRequest,
    LegalForm,
    PermitKind,
    RecipientPermit,
    Requester,
    SignerRole,
)

# An invented document: the file a requester would have sent.
INVENTED_PDF = b"%PDF-1.4\n% An invented example document of the development data.\n%%EOF\n"


@dataclass(frozen=True)
class SeedPermit:
    kind: PermitKind
    issuer: str
    reference: str  # contains /DEV/ or "(invented example)"
    valid_from: date
    issuer_country: str = "CZ"
    expires_on: date | None = None
    covers: str = ""
    quantity_allowed: int | None = None
    sendings_allowed: int | None = None
    gmo_category: int | None = None
    risk_group: int | None = None


@dataclass(frozen=True)
class SeedRequester:
    institution: str
    country: str
    lab_evidence: str
    scientist: services.ContactInput
    legal_form: LegalForm = LegalForm.LEGAL_PERSON
    registration_number: str = ""
    lab_confirmed_on: date = date(2026, 10, 1)
    permits: tuple[SeedPermit, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SeedRequest:
    institution: str
    end_use: str  # unique per lab: the request's natural key here
    use: Use
    containment_level: int
    lines: tuple[tuple[Strain, int], ...]
    accept: bool = True
    # Approved by the same person, which reserves its vials: a request ready to ship.
    approve: bool = False


def requester(access: Access, lab: Lab, data: SeedRequester) -> Requester:
    found = Requester.objects.filter(lab=lab, institution=data.institution).first()
    if found is None:
        found = services.requester_create(
            access=access,
            lab=lab,
            data=services.RequesterInput(
                contact=data.scientist,
                institution=data.institution,
                legal_form=data.legal_form,
                country=data.country,
                lab_evidence=data.lab_evidence,
                lab_confirmed_on=data.lab_confirmed_on,
                registration_number=data.registration_number,
            ),
        )
    for permit in data.permits:
        if RecipientPermit.objects.filter(
            requester=found, kind=permit.kind, reference=permit.reference
        ).exists():
            continue
        services.permit_add(
            access=access,
            requester=found,
            data=services.PermitInput(
                kind=permit.kind,
                issuer=permit.issuer,
                issuer_country=permit.issuer_country,
                reference=permit.reference,
                valid_from=permit.valid_from,
                expires_on=permit.expires_on,
                covers=permit.covers,
                quantity_allowed=permit.quantity_allowed,
                sendings_allowed=permit.sendings_allowed,
                gmo_category=permit.gmo_category,
                risk_group=permit.risk_group,
                document=services.DocumentInput(INVENTED_PDF),
            ),
        )
    return found


def request(access: Access, lab: Lab, data: SeedRequest) -> DistributionRequest:
    found = DistributionRequest.objects.filter(lab=lab, end_use=data.end_use).first()
    if found is not None:
        return found
    made = services.request_submit(
        access=access,
        lab=lab,
        data=services.NewRequest(
            requester=Requester.objects.get(lab=lab, institution=data.institution),
            use=data.use,
            end_use=data.end_use,
            containment_level=data.containment_level,
            lines=[services.LineInput(strain, quantity) for strain, quantity in data.lines],
        ),
    )
    if data.accept:
        for mta_id in sorted({line.mta_id for line in made.lines.all() if line.mta_id}):
            services.acceptance_record(
                access=access,
                request=made,
                data=services.AcceptanceInput(
                    mta_id=mta_id,
                    signer=services.ContactInput("Invented Signatory", "signatory@example.org"),
                    signer_role=SignerRole.HEAD_OF_INSTITUTION,
                    authorised_signatory=True,
                    accepted_on=date(2026, 10, 2),
                    document=services.DocumentInput(INVENTED_PDF),
                ),
            )
    if data.approve:
        made = services.request_approve(access=access, request=made)
    return made

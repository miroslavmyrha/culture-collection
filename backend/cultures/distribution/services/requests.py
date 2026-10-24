"""Requests with their lines, and the MTA acceptances recorded on them."""

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    MTA_ACCEPTANCE_RECORDED,
    PERSONAL_CHANGED,
    REQUEST_LINE_ADDED,
    REQUEST_SUBMITTED,
)
from cultures.biosafety.policy import permit_today
from cultures.deposits.models import Contact, DepositTerms
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.strains.models import Strain
from cultures.strains.selectors import regulating_restrictions

from .. import policy
from ..models import (
    ACCEPTANCE_UNIQUE,
    COUNTER_UNIQUE,
    MAX_VIALS_PER_LINE,
    REQUEST_NUMBER_UNIQUE,
    DistributionRequest,
    MtaAcceptance,
    RequestCounter,
    Requester,
    RequestLine,
    RequestStatus,
)
from ._shared import (
    ACCEPTANCE,
    LINE,
    REQUEST,
    _checked_contact,
    _checked_document,
    _locked,
    _locked_request,
    _require,
    _save,
    _store,
)
from .errors import (
    AcceptanceExists,
    DestinationRefused,
    InvalidDistribution,
    NumberTaken,
    WrongState,
)
from .inputs import (
    AcceptanceInput,
    NewRequest,
)

# A request holds at most this many strains: a bigger order is two requests.
MAX_LINES = 20


# Requests.


def _checked_request(data: NewRequest) -> NewRequest:
    end_use = data.end_use.strip()
    if not end_use:
        raise InvalidDistribution("Say what the recipient will use it for.", attr="end_use")
    if not 1 <= data.containment_level <= 4:  # noqa: PLR2004
        raise InvalidDistribution("A containment level is 1 to 4.", attr="containment_level")
    if not data.lines:
        raise InvalidDistribution("Add a strain.", attr="lines")
    if len(data.lines) > MAX_LINES:
        raise InvalidDistribution(f"A request has at most {MAX_LINES} strains.", attr="lines")
    seen: set[int] = set()
    for i, line in enumerate(data.lines):
        if line.strain.pk in seen:
            raise InvalidDistribution("This strain is listed twice.", attr=f"lines.{i}.strain")
        seen.add(line.strain.pk)
        if not 1 <= line.quantity <= MAX_VIALS_PER_LINE:
            raise InvalidDistribution(
                f"Ask for 1 to {MAX_VIALS_PER_LINE} vials.", attr=f"lines.{i}.quantity"
            )
    return NewRequest(
        requester=data.requester,
        use=data.use,
        end_use=end_use,
        containment_level=data.containment_level,
        lines=tuple(data.lines),
    )


def _next_number(lab: Lab, year: int) -> int:
    """The lab's next number in the year, from its counter row (caller holds the lab lock)."""
    counter = RequestCounter.objects.select_for_update().filter(lab=lab, year=year).first()
    if counter is None:
        counter = RequestCounter(lab=lab, year=year)
        _save(counter, {COUNTER_UNIQUE: NumberTaken()})
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return counter.last_number


def request_submit(*, access: Access, lab: Lab, data: NewRequest) -> DistributionRequest:
    """A request as the requester sent it, with its lines. Each line keeps the terms of the
    strain's deposit in force now and their MTA version. Refused outright when the requester's
    country is outside the EU."""
    data = _checked_request(data)
    with audited_atomic():
        locked_lab = lock_lab(lab.pk)
        _require(access, locked_lab.pk, Perm.MANAGE_DISTRIBUTION)
        requester = _locked(Requester, data.requester.pk)
        if requester.lab_id != locked_lab.pk:
            raise InvalidDistribution("Invalid requester.", attr="requester")
        if Contact.objects.filter(pk=requester.contact_id, erased_at__isnull=False).exists():
            raise InvalidDistribution("This requester's contact was erased.", attr="requester")
        strains = {
            s.pk: s
            for s in Strain.objects.select_for_update()
            .filter(pk__in=[line.strain.pk for line in data.lines], lab=locked_lab)
            .order_by("pk")
        }
        regulated = regulating_restrictions().filter(strain_id__in=strains).exists()
        refusal = policy.destination_finding(requester.country, regulated=regulated)
        if refusal is not None:
            raise DestinationRefused(refusal.sentence, code=refusal.code, attr="requester")
        terms = {
            t.deposit.strain_id: t
            for t in DepositTerms.objects.select_related("deposit", "mta").filter(
                deposit__strain_id__in=strains, is_active=True
            )
        }
        for i, line in enumerate(data.lines):
            if line.strain.pk not in strains:
                raise InvalidDistribution("Invalid strain.", attr=f"lines.{i}.strain")
            if line.strain.pk not in terms:
                raise InvalidDistribution(
                    "This strain has no terms: it came from no deposit.",
                    code="no_terms",
                    attr=f"lines.{i}.strain",
                )
        year = permit_today().year
        request = DistributionRequest(
            lab=locked_lab,
            year=year,
            number=_next_number(locked_lab, year),
            requester=requester,
            destination_country=requester.country,
            use=data.use,
            end_use=data.end_use,
            containment_level=data.containment_level,
            submitted_by=access.user,
        )
        _save(request, {REQUEST_NUMBER_UNIQUE: NumberTaken()})
        record_event(
            REQUEST_SUBMITTED,
            Change(
                REQUEST,
                request.public_id,
                {
                    "number": [None, request.label],
                    "requester": [None, str(requester.public_id)],
                    "destination_country": [None, request.destination_country],
                    "use": [None, request.use],
                    "end_use": [None, request.end_use],
                    "containment_level": [None, request.containment_level],
                    "status": [None, request.status],
                },
                lab_id=locked_lab.pk,
            ),
        )
        for line in data.lines:
            strain, pinned = strains[line.strain.pk], terms[line.strain.pk]
            row = RequestLine.objects.create(
                lab=locked_lab,
                request=request,
                strain=strain,
                quantity=line.quantity,
                terms=pinned,
                mta=pinned.mta,
            )
            mta = (
                None
                if pinned.mta is None
                else {
                    "public_id": str(pinned.mta.public_id),
                    "code": pinned.mta.code,
                    "version": pinned.mta.version,
                }
            )
            record_event(
                REQUEST_LINE_ADDED,
                Change(
                    LINE,
                    row.public_id,
                    {
                        "request": [None, str(request.public_id)],
                        "quantity": [None, row.quantity],
                        "terms": [
                            None,
                            {"version": pinned.version, "public_id": str(pinned.public_id)},
                        ],
                        "mta": [None, mta],
                    },
                    lab_id=locked_lab.pk,
                    strain_id=strain.public_id,
                ),
            )
    return request


def acceptance_record(
    *, access: Access, request: DistributionRequest, data: AcceptanceInput
) -> MtaAcceptance:
    """The requester accepted an MTA version a line is pinned to, signed by `signer`. Recorded
    from the signed copy, which is kept as the evidence."""
    signer = _checked_contact(data.signer, "signer_", address=False)
    _checked_document(data.document)
    if data.accepted_on > permit_today():
        raise InvalidDistribution("This date is in the future.", attr="accepted_on")
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        if locked.status != RequestStatus.SUBMITTED:
            raise WrongState("An acceptance is recorded while the request waits for a decision.")
        line = (
            RequestLine.objects.select_related("mta")
            .filter(request=locked, mta_id=data.mta_id)
            .first()
        )
        if line is None or line.mta is None:
            raise InvalidDistribution("Choose an MTA version of this request.", attr="mta")
        person = Contact.objects.create(
            lab_id=locked.lab_id, name=signer.name, email=signer.email, postal_address=""
        )
        document = _store(locked.lab_id, data.document)
        acceptance = MtaAcceptance(
            lab_id=locked.lab_id,
            request=locked,
            mta=line.mta,
            signer=person,
            signer_role=data.signer_role,
            authorised_signatory=data.authorised_signatory,
            accepted_on=data.accepted_on,
            document=document,
        )
        _save(acceptance, {ACCEPTANCE_UNIQUE: AcceptanceExists()})
        record_event(
            MTA_ACCEPTANCE_RECORDED,
            Change(
                ACCEPTANCE,
                acceptance.public_id,
                {
                    "request": [None, str(locked.public_id)],
                    "mta": [None, {"code": line.mta.code, "version": line.mta.version}],
                    "signer": PERSONAL_CHANGED,
                    "signer_role": [None, acceptance.signer_role],
                    "authorised_signatory": [None, acceptance.authorised_signatory],
                    "accepted_on": [None, acceptance.accepted_on.isoformat()],
                    "document": [
                        None,
                        {"public_id": str(document.public_id), "sha256": document.sha256},
                    ],
                },
                lab_id=locked.lab_id,
            ),
        )
    return acceptance

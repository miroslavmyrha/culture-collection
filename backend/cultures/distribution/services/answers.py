"""The depositor's answer for a use the terms leave on request to the depositor (#144)."""

from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import DEPOSITOR_ANSWER_RECORDED
from cultures.biosafety.policy import permit_today
from cultures.deposits.models import Decision, TermsUse, Use
from cultures.labs.access import Access
from cultures.labs.permissions import Perm

from ..models import DepositorAnswer, DistributionRequest, RequestLine, RequestStatus
from ._shared import LINE, _checked_document, _locked_request, _save, _store
from .decisions import _reject
from .errors import DepositorAnswerExists, InvalidDistribution, WrongState
from .inputs import DepositorAnswerInput

# The unique index of the one-to-one line column (PostgreSQL's name for an inline UNIQUE).
ANSWER_UNIQUE = "distribution_depositoranswer_line_id_key"


def depositor_answer_record(
    *, access: Access, request: DistributionRequest, data: DepositorAnswerInput
) -> DepositorAnswer:
    """What the depositor answered for one line whose pinned terms leave the request's use on
    request (s3, section 6: such a use passes only with a recorded approval of the depositor).
    The evidence is the depositor's letter or e-mail as a file, a note, or both. Once per line.
    A yes lets the line pass that gate (policy.evaluate); a no rejects the whole request in the
    same transaction with the answer as the reason: lines are not rejected one by one (ADR 0008,
    amendment of 2026-10-27)."""
    note = data.note.strip()
    if data.document is not None:
        _checked_document(data.document)
    elif not note:
        raise InvalidDistribution(
            "Give the depositor's answer as a file, a note, or both.", attr="note"
        )
    if data.answered_on > permit_today():
        raise InvalidDistribution("This date is in the future.", attr="answered_on")
    with audited_atomic():
        locked = _locked_request(access, request, Perm.MANAGE_DISTRIBUTION)
        if locked.status != RequestStatus.SUBMITTED:
            raise WrongState("An answer is recorded while the request waits for a decision.")
        line = (
            RequestLine.objects.select_related("strain")
            .filter(request=locked, pk=data.line_id)
            .first()
        )
        if line is None:
            raise InvalidDistribution("Choose a strain of this request.", attr="line")
        use = Use(locked.use)
        # The twin of the trigger's rule (migration 0013); tests/test_depositor_answer.py
        # asserts both agree for every decision.
        decision = (
            TermsUse.objects.filter(terms_id=line.terms_id, use=use)
            .values_list("decision", flat=True)
            .first()
        )
        if decision != Decision.ON_REQUEST:
            raise InvalidDistribution(
                f"The terms of {line.strain.accession_number} do not leave"
                f" {use.label.lower()} to the depositor.",
                code="not_on_request",
                attr="line",
            )
        document = None if data.document is None else _store(locked.lab_id, data.document)
        answer = DepositorAnswer(
            lab_id=locked.lab_id,
            line=line,
            agreed=data.agreed,
            answered_on=data.answered_on,
            note=note,
            document=document,
            recorded_by=access.user,
            recorded_at=timezone.now(),
        )
        _save(answer, {ANSWER_UNIQUE: DepositorAnswerExists()})
        record_event(
            DEPOSITOR_ANSWER_RECORDED,
            Change(
                LINE,
                line.public_id,
                {
                    "answer": [None, str(answer.public_id)],
                    "agreed": [None, answer.agreed],
                    "answered_on": [None, answer.answered_on.isoformat()],
                    "note": [None, answer.note],
                    "document": [
                        None,
                        None
                        if document is None
                        else {"public_id": str(document.public_id), "sha256": document.sha256},
                    ],
                },
                lab_id=locked.lab_id,
                strain_id=line.strain.public_id,
            ),
        )
        if not answer.agreed:
            said = f": {note}" if note else "."
            _reject(
                access,
                locked,
                f"The depositor declined {use.label.lower()} of"
                f" {line.strain.accession_number} (answer of"
                f" {answer.answered_on.isoformat()}){said}",
            )
    return answer

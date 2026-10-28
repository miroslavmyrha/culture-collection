"""The depositor's answer for a use the terms leave on request (#144, walkthrough C9): without
one nobody approves the line, a yes lets whoever may approve the rest approve it, a no rejects
the request with the answer as the reason. Then the refusals, who may record it, the trigger,
and the twin rule ("the pinned terms leave the use on request") tried on both writers."""

from collections.abc import Callable
from datetime import date, timedelta
from functools import partial
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import Forbidden
from cultures.deposits.models import Decision, Use
from cultures.deposits.tests.support import ALL_PERMITTED, DUAL_USE
from cultures.distribution import services
from cultures.distribution.models import (
    DepositorAnswer,
    DistributionRequest,
    Requester,
    RequestLine,
    RequestStatus,
)
from cultures.distribution.policy import Severity, evaluate
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.strains.models import Strain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import (
    ON_REQUEST_USES,
    PDF,
    Supply,
    accept_mtas,
    answer,
    approve,
    as_actor,
    submit,
)
from .test_services import refused

pytestmark = pytest.mark.django_db

Commercial = Callable[..., DistributionRequest]


@pytest.fixture
def commercial(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> Commercial:
    """A request for commercial research, its MTA accepted, of `strains` (by default one whose
    terms leave that use on request to the depositor)."""

    def make(*strains: Strain) -> DistributionRequest:
        chosen = strains or (supply(uses=ON_REQUEST_USES),)
        request = submit(
            curator, lab, requester, [(s, 1) for s in chosen], use=Use.RESEARCH_COMMERCIAL
        )
        accept_mtas(curator, request)
        return request

    return make


def codes(request: DistributionRequest) -> dict[str, Severity]:
    return {f.code: f.severity for f in evaluate(request, permit_today()).findings}


def events_after(pk: int) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(pk__gt=pk).order_by("pk"))


def last_event() -> int:
    return AuditEvent.objects.order_by("-pk").values_list("pk", flat=True).first() or 0


# What an answer does to the request.


def test_without_an_answer_neither_a_curator_nor_a_manager_approves_it(
    commercial: Commercial, curator: User, manager: User
) -> None:
    request = commercial()
    assert codes(request) == {"use_on_request": Severity.BLOCK}
    for actor in (curator, manager):
        refused(
            services.RequestBlocked,
            "request_blocked",
            partial(approve, actor, request, "The depositor agreed by phone."),
        )


def test_a_yes_with_its_file_lets_a_curator_approve(commercial: Commercial, curator: User) -> None:
    request = commercial()
    line = request.lines.get()
    start = last_event()
    recorded = answer(curator, request)
    assert recorded.document is not None and bytes(recorded.document.content) == PDF
    assert (recorded.agreed, recorded.answered_on, recorded.recorded_by) == (
        True,
        date(2026, 10, 2),
        curator,
    )
    [event] = events_after(start)
    assert (event.event_type, event.subject_type, event.subject_id) == (
        "depositor_answer_recorded",
        "request_line",
        line.public_id,
    )
    assert event.strain_id == line.strain.public_id
    assert event.changes["agreed"] == [None, True]
    assert event.changes["document"][1]["sha256"] == recorded.document.sha256
    assert codes(request) == {}
    approved = approve(curator, request)
    assert (approved.status, approved.decided_by, approved.decision_reason) == (
        RequestStatus.APPROVED,
        curator,
        "",
    )


def test_a_yes_lowers_nobody_a_regulated_line_still_needs_a_manager(
    commercial: Commercial, supply: Supply, mockia: Taxon, curator: User, manager: User
) -> None:
    request = commercial(supply(mockia, restrictions=[DUAL_USE], uses=ON_REQUEST_USES))
    answer(curator, request)
    assert codes(request) == {"regulated": Severity.MANAGER}
    refused(
        services.ManagerRequired, "manager_approval_required", lambda: approve(curator, request)
    )
    approved = approve(manager, request, "Dual-use inside the EU needs no licence.")
    assert approved.status == RequestStatus.APPROVED


def test_a_yes_counts_for_its_own_line_only(
    commercial: Commercial, supply: Supply, curator: User
) -> None:
    request = commercial(supply(uses=ON_REQUEST_USES), supply(uses=ON_REQUEST_USES))
    first, second = request.lines.order_by("pk")
    answer(curator, request, line_id=first.pk)
    [finding] = evaluate(request, permit_today()).findings
    assert (finding.code, finding.line) == ("use_on_request", second)


@pytest.mark.parametrize(
    ("note", "said"),
    [
        ("They keep commercial use for themselves.", ": They keep commercial use for themselves."),
        ("", "."),
    ],
)
def test_a_no_rejects_the_request_with_the_answer_as_the_reason(
    commercial: Commercial, curator: User, note: str, said: str
) -> None:
    request = commercial()
    number = request.lines.get().strain.accession_number
    start = last_event()
    answer(curator, request, agreed=False, note=note)
    request.refresh_from_db()
    reason = f"The depositor declined commercial research of {number} (answer of 2026-10-02){said}"
    assert (request.status, request.decided_by, request.decision_reason) == (
        RequestStatus.REJECTED,
        curator,
        reason,
    )
    recorded, rejected = events_after(start)
    assert (recorded.event_type, recorded.changes["agreed"]) == (
        "depositor_answer_recorded",
        [None, False],
    )
    assert (rejected.event_type, rejected.reason) == ("request_rejected", reason)


def test_a_no_written_beside_the_service_blocks_the_approval(
    commercial: Commercial, curator: User, lab: Lab
) -> None:
    """The service rejects the request with a no; a no another writer left on a waiting request
    still blocks its approval (policy.py, use_declined_by_depositor)."""
    request = commercial()
    DepositorAnswer.objects.create(
        lab=lab,
        line=request.lines.get(),
        agreed=False,
        answered_on=date(2026, 10, 2),
        note="Declined.",
        recorded_by=curator,
        recorded_at=timezone.now(),
    )
    assert codes(request) == {"use_declined_by_depositor": Severity.BLOCK}
    refused(services.RequestBlocked, "request_blocked", lambda: approve(curator, request))


# Refusals.


def test_the_answer_is_recorded_once(commercial: Commercial, curator: User) -> None:
    request = commercial()
    answer(curator, request)
    refused(
        services.DepositorAnswerExists, "depositor_answer_exists", lambda: answer(curator, request)
    )


def test_an_answer_waits_with_its_request(commercial: Commercial, curator: User) -> None:
    request = commercial()
    with as_actor(curator):
        services.request_reject(access=access_for(curator), request=request, reason="duplicate")
    refused(services.WrongState, "request_state", lambda: answer(curator, request))


def test_a_line_whose_terms_permit_the_use_takes_no_answer(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)], use=Use.RESEARCH_COMMERCIAL)
    refused(
        services.InvalidDistribution, "not_on_request", lambda: answer(curator, request), "line"
    )


def test_a_line_of_another_request_is_refused(commercial: Commercial, curator: User) -> None:
    request, other = commercial(), commercial()
    line = other.lines.get().pk
    refused(
        services.InvalidDistribution,
        "invalid",
        lambda: answer(curator, request, line_id=line),
        "line",
    )


@pytest.mark.parametrize(
    ("changes", "attr"),
    [
        ({"note": "", "document": None}, "note"),
        ({"note": "   ", "document": None}, "note"),
        ({"document": services.DocumentInput(b"GIF89a")}, "file"),
        ({"answered_on": "tomorrow"}, "answered_on"),
    ],
)
def test_an_answer_needs_evidence_a_known_file_type_and_a_past_day(
    commercial: Commercial, curator: User, changes: dict[str, Any], attr: str
) -> None:
    if changes.get("answered_on") == "tomorrow":
        changes = {"answered_on": permit_today() + timedelta(days=1)}
    request = commercial()
    refused(
        services.InvalidDistribution,
        "invalid",
        lambda: answer(curator, request, **changes),
        attr,
    )


def test_a_note_alone_or_a_file_alone_is_evidence(commercial: Commercial, curator: User) -> None:
    assert answer(curator, commercial(), document=None).document is None
    assert answer(curator, commercial(), note="").note == ""


@pytest.mark.parametrize("role", ["viewer", "technician"])
def test_only_curators_and_managers_record_it(
    commercial: Commercial, role: str, request: pytest.FixtureRequest
) -> None:
    person: User = request.getfixturevalue(role)
    target = commercial()
    refused(Forbidden, "permission_denied", lambda: answer(person, target))


def test_a_manager_records_it_too(commercial: Commercial, manager: User) -> None:
    assert answer(manager, commercial()).recorded_by == manager


# The database.


def raw(sql: str) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql)


def test_the_trigger_keeps_an_answer_as_recorded(commercial: Commercial, curator: User) -> None:
    answer(curator, commercial())
    for sql in (
        "UPDATE distribution_depositoranswer SET agreed = false",
        "UPDATE distribution_depositoranswer SET note = 'changed'",
        "DELETE FROM distribution_depositoranswer",
    ):
        with pytest.raises(DatabaseError, match="never changes"):
            raw(sql)


def test_the_trigger_takes_an_answer_only_while_the_request_waits(
    commercial: Commercial, curator: User, lab: Lab
) -> None:
    request = commercial()
    with as_actor(curator):
        services.request_reject(access=access_for(curator), request=request, reason="duplicate")
    with (
        pytest.raises(DatabaseError, match="a line of a waiting request of its lab"),
        transaction.atomic(),
    ):
        written(request.lines.get(), lab, curator)


def written(line: RequestLine, lab: Lab, user: User) -> DepositorAnswer:
    return DepositorAnswer.objects.create(
        lab=lab,
        line=line,
        agreed=True,
        answered_on=date(2026, 10, 2),
        note="The depositor's e-mail.",
        recorded_by=user,
        recorded_at=timezone.now(),
    )


# "The pinned terms leave the request's use on request" is written twice: the service's
# not_on_request and the trigger of migration 0013 (ADR 0010, proposed). Every decision a terms
# use may have, tried on both: each accepts exactly when the decision is on request.


class Undo(Exception):
    pass


@pytest.mark.parametrize("decision", Decision.values)
def test_the_trigger_and_the_service_agree_on_a_use_on_request(
    commercial: Commercial, supply: Supply, curator: User, lab: Lab, decision: str
) -> None:
    assert set(Decision.values) == {"permit", "deny", "on_request"}  # a new one needs a case
    uses = tuple(
        (use, Decision(decision) if use == Use.RESEARCH_COMMERCIAL else d)
        for use, d in ALL_PERMITTED
    )
    request = commercial(supply(uses=uses))
    line = request.lines.get()
    try:
        with transaction.atomic():
            written(line, lab, curator)
            raise Undo  # taken: undone, so the service writes the line's one answer next
    except Undo:
        by_trigger = True
    except DatabaseError:
        by_trigger = False
    try:
        answer(curator, request)
        by_service = True
    except services.InvalidDistribution as refusal:
        assert (refusal.code, refusal.attr) == ("not_on_request", "line")
        by_service = False
    assert by_trigger == by_service == (decision == Decision.ON_REQUEST)

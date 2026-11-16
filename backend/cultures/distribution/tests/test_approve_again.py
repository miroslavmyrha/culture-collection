"""A finding that asks for a manager and arises after the approval (#263, R-DIST-03).

The approval records the manager findings it decided. A restriction added to a strain, a risk
group raised or a requester's work permit ended can bring a new one; then nothing is prepared,
confirmed or shipped until a manager approves the request again, with a reason. The vials stay
reserved. Examples are the invented Mockia vulgaris (dual use) and Exempli gratia.
"""

from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction

from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import RuleViolation
from cultures.distribution import services
from cultures.distribution.models import (
    DistributionRequest,
    FindingDecision,
    PermitKind,
    Requester,
    RequestStatus,
)
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.strains import services as strains
from cultures.strains.tests.conftest import DUAL_USE
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import (
    Regulated,
    Supply,
    accept_mtas,
    add_permit,
    approve,
    as_actor,
    confirm,
    prepare,
    reserved,
    ship,
    submit,
)
from .test_services import events_since, last_pk, refused

pytestmark = pytest.mark.django_db
REASON = "The dual-use entry was read in Annex I after the approval (invented example)."


def approved_by_a_curator(
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    taxon: Taxon,
    *,
    containment_level: int = 2,
    **strain: object,
) -> DistributionRequest:
    """A request a curator approved alone: no finding asked for a manager then."""
    chosen = supply(taxon, vials=6, **strain)
    request = submit(curator, lab, requester, [(chosen, 1)], containment_level=containment_level)
    accept_mtas(curator, request)
    return approve(curator, request)


def restricted(actor: User, request: DistributionRequest) -> None:
    with as_actor(actor):
        strains.strain_restriction_add(
            access=access_for(actor),
            strain=request.lines.get().strain,
            restriction=DUAL_USE,
            reason="Read in Annex I.",
        )


def approve_again(actor: User, request: DistributionRequest, reason: str = REASON) -> None:
    with as_actor(actor):
        services.request_approve_again(access=access_for(actor), request=request, reason=reason)


@pytest.fixture
def others(lab: Lab) -> tuple[User, User]:
    """Two more curators: two people besides the approver for the two-person shipment."""
    return member_of(lab, Role.CURATOR, "second"), member_of(lab, Role.CURATOR, "third")


# The refusal.


@pytest.mark.rule("R-DIST-03")
def test_a_restriction_added_after_the_approval_stops_the_preparation(
    *, curator: User, lab: Lab, requester: Requester, supply: Supply, mockia: Taxon,
    others: tuple[User, User],
) -> None:  # fmt: skip
    request = approved_by_a_curator(curator, lab, requester, supply, mockia)
    restricted(curator, request)
    error = refused(services.ApproveAgain, "approve_again", lambda: prepare(others[0], request))
    assert "is regulated" in error.detail
    request.refresh_from_db()
    assert request.status == RequestStatus.APPROVED
    assert len(reserved(request)) == 1  # the vials stay reserved


@pytest.mark.rule("R-DIST-03")
def test_a_risk_group_raised_after_the_approval_stops_the_one_step_shipment(
    *, curator: User, lab: Lab, requester: Requester, supply: Supply, exempli: Taxon,
) -> None:  # fmt: skip
    add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT, risk_group=3)
    request = approved_by_a_curator(
        curator, lab, requester, supply, exempli, containment_level=3, risk_group=2
    )
    with as_actor(curator):
        strains.strain_set_risk_group(
            access=access_for(curator),
            strain=request.lines.get().strain,
            risk_group=3,
            basis="A new identification (invented example).",
            reason="Identified again.",
        )
    error = refused(services.ApproveAgain, "approve_again", lambda: ship(curator, request))
    assert "Category A" in error.detail


@pytest.mark.rule("R-DIST-03")
def test_a_work_permit_ended_after_the_approval_stops_the_one_step_shipment(
    *, curator: User, lab: Lab, requester: Requester, supply: Supply, exempli: Taxon,
) -> None:  # fmt: skip
    work = add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT)
    request = approved_by_a_curator(curator, lab, requester, supply, exempli, risk_group=2)
    with as_actor(curator):
        services.permit_end(
            access=access_for(curator),
            permit=work,
            ended_on=permit_today() - timedelta(days=1),
            reason="Surrendered (invented example).",
        )
    refused(services.ApproveAgain, "approve_again", lambda: ship(curator, request))


@pytest.mark.rule("R-DIST-03")
def test_a_finding_decided_at_the_approval_is_not_asked_again(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)  # a manager approved the dual-use finding
    confirm(manager, request)
    request.refresh_from_db()
    assert request.status == RequestStatus.SHIPPED


@pytest.mark.rule("R-DIST-03")
def test_a_finding_on_another_line_is_another_finding(
    *, curator: User, approver: User, lab: Lab, requester: Requester, supply: Supply,
    mockia: Taxon, others: tuple[User, User],
) -> None:  # fmt: skip
    """A manager decided "regulated" for one line; a second line restricted later is new."""
    first = supply(mockia, restrictions=[DUAL_USE], vials=6)
    second = supply(mockia, vials=6)
    request = submit(curator, lab, requester, [(first, 1), (second, 1)])
    accept_mtas(curator, request)
    approve(approver, request, "Dual-use inside the EU needs no licence.")
    with as_actor(curator):
        strains.strain_restriction_add(
            access=access_for(curator), strain=second, restriction=DUAL_USE, reason="Read."
        )
    refused(services.ApproveAgain, "approve_again", lambda: prepare(others[0], request))


# The second approval.


@pytest.mark.rule("R-DIST-03")
def test_a_manager_approves_again_and_two_other_people_ship_it(
    *, curator: User, manager: User, lab: Lab, requester: Requester, supply: Supply,
    mockia: Taxon, others: tuple[User, User],
) -> None:  # fmt: skip
    request = approved_by_a_curator(curator, lab, requester, supply, mockia)
    restricted(curator, request)
    start = last_pk()
    approve_again(manager, request)
    recorded = events_since(start)
    assert [(e.event_type, e.reason) for e in recorded] == [("request_approved_again", REASON)]
    assert recorded[0].changes == {"findings": [None, ["regulated"]]}
    decided = FindingDecision.objects.filter(request=request).order_by("pk").last()
    assert decided is not None
    assert (decided.decided_by, decided.reason) == (manager, REASON)
    request.refresh_from_db()
    assert (request.status, request.decided_by) == (RequestStatus.APPROVED, curator)
    prepare(others[0], request)
    confirm(others[1], request)
    request.refresh_from_db()
    assert request.status == RequestStatus.SHIPPED


@pytest.mark.rule("R-DIST-03")
def test_who_approved_again_does_not_confirm(
    *, curator: User, manager: User, lab: Lab, requester: Requester, supply: Supply,
    mockia: Taxon, others: tuple[User, User],
) -> None:  # fmt: skip
    request = approved_by_a_curator(curator, lab, requester, supply, mockia)
    restricted(curator, request)
    approve_again(manager, request)
    prepare(others[0], request)
    refused(services.ConfirmOwnApproval, "confirm_own_approval", lambda: confirm(manager, request))


@pytest.mark.rule("R-DIST-03")
def test_a_curator_does_not_approve_again_and_a_manager_gives_a_reason(
    *, curator: User, manager: User, lab: Lab, requester: Requester, supply: Supply,
    mockia: Taxon,
) -> None:  # fmt: skip
    request = approved_by_a_curator(curator, lab, requester, supply, mockia)
    restricted(curator, request)
    refused(
        services.ManagerRequired,
        "manager_approval_required",
        lambda: approve_again(curator, request),
    )
    refused(
        RuleViolation,
        "reason_required",
        lambda: approve_again(manager, request, "  "),
        attr="reason",
    )


def test_nothing_to_approve_again_when_every_finding_was_decided(
    *, manager: User, regulated: Regulated
) -> None:
    request = regulated()
    refused(
        services.NothingToApproveAgain,
        "nothing_to_approve_again",
        lambda: approve_again(manager, request),
    )


def test_only_an_approved_request_is_approved_again(
    *, curator: User, manager: User, regulated: Regulated
) -> None:
    request = regulated(prepared_by=curator)  # awaiting confirmation: withdraw it first
    refused(services.WrongState, "request_state", lambda: approve_again(manager, request))


# The table.


def test_the_table_keeps_a_decision_as_it_was_written(
    *, curator: User, approver: User, regulated: Regulated
) -> None:
    request = regulated()
    decided = FindingDecision.objects.get(request=request)
    assert (decided.key, decided.decided_by) == (
        f"regulated:{request.lines.get().public_id}",
        approver,
    )
    for statement in (
        "UPDATE distribution_findingdecision SET reason = 'x' WHERE id = %s",
        "DELETE FROM distribution_findingdecision WHERE id = %s",
    ):
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(statement, [decided.pk])

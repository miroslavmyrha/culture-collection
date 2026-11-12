"""A lower risk group takes two steps, by two people (#174, ADR 0009).

A risk group gates the rules around the strain: the cap of a box its vials may sit in, the
containment the requester must declare, the shipment class. One person lowering it took the
strain out of those rules, so lowering is now proposed by someone who manages strains and
confirmed by a manager other than the proposer, with the basis the lower group rests on; until
the confirmation every rule reads the higher group. A raise stays one person's and goes one step
at a time. The database holds all of it against every writer.

Government order 361/2007 Sb., Annex 7, Part A: „Biologické činitele, které nebyly zařazeny do
skupin 2 až 4 seznamu, nejsou automaticky zařazeny do skupiny 1.“ An agent missing from the list
is not thereby group 1, so every group rests on a stated basis, never on the absence of an entry.
The step rule and the two people are the project's own.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.db import IntegrityError, InternalError, connection, transaction
from django.db.backends.utils import CursorWrapper
from django.utils import timezone

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel, RowChange
from cultures.audit.tests.conftest import refused as refused_sql
from cultures.core.exceptions import DomainError, Forbidden, RuleViolation
from cultures.core.testing import assert_problem, logged_in
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Perm, Role, role_has
from cultures.labs.tests.conftest import member_of
from cultures.strains import services
from cultures.strains.models import RiskGroupProposal, Strain
from cultures.users.models import User

from .conftest import ACCESSION_BASIS, STRAINS_URL, MakeStrain, at_commit, refused_at_commit

pytestmark = pytest.mark.django_db

BASIS = "NV 361/2007 Sb., Příloha 7, část A, tabulka č. 1: the agent is not in groups 2 to 4."
LOWER = "Reassessed against the annex."


def as_(user: User) -> Any:
    return audit_context(channel=Channel.API, actor=user, request_id="req-risk")


@pytest.fixture
def group2(make_strain: MakeStrain) -> Strain:
    """A strain accessioned at risk group 2: there is a group to lower."""
    return make_strain(risk_group=2)


def propose(user: User, strain: Strain, group: int = 1, basis: str = BASIS) -> RiskGroupProposal:
    with as_(user):
        return services.strain_risk_group_lower_propose(
            access=access_for(user), strain=strain, risk_group=group, basis=basis, reason=LOWER
        )


def confirm(user: User, strain: Strain, proposal: Any) -> Strain:
    with as_(user):
        return services.strain_risk_group_lower_confirm(
            access=access_for(user), strain=strain, proposal=proposal
        )


def withdraw(user: User, strain: Strain, proposal: Any, reason: str = "Listed after all.") -> Any:
    with as_(user):
        return services.strain_risk_group_lower_withdraw(
            access=access_for(user), strain=strain, proposal=proposal, reason=reason
        )


def raise_group(user: User, strain: Strain, group: int, basis: str = BASIS) -> Strain:
    with as_(user):
        return services.strain_set_risk_group(
            access=access_for(user), strain=strain, risk_group=group, basis=basis, reason="Raised."
        )


def snapshot() -> tuple[Any, ...]:
    rows = tuple(
        list(m._default_manager.order_by("pk").values()) for m in (Strain, RiskGroupProposal)
    )
    return (*rows, AuditEvent.objects.count(), RowChange.objects.count())


def refused(error: type[DomainError], code: str, call: Callable[[], object]) -> DomainError:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert raised.value.code == code
    assert snapshot() == before
    return raised.value


# The two steps.


@pytest.mark.rule("R-RISK-06")
def test_one_person_no_longer_lowers_a_risk_group(curator: User, group2: Strain) -> None:
    error = refused(
        services.RiskGroupNeedsSecondPerson,
        "risk_group_second_person_required",
        lambda: raise_group(curator, group2, 1),
    )
    assert error.status_code == 422
    assert Strain.objects.get(pk=group2.pk).risk_group == 2


@pytest.mark.rule("R-RISK-06")
def test_a_proposal_changes_nothing_for_the_strain(curator: User, group2: Strain) -> None:
    proposal = propose(curator, group2, basis=f"  {BASIS}  ")
    group2.refresh_from_db()
    # #169: the strain still reads what the accession recorded, untouched by the proposal.
    assert (group2.risk_group, group2.risk_group_basis) == (2, ACCESSION_BASIS)
    assert group2.risk_group_set_at is not None
    assert (proposal.risk_group, proposal.from_risk_group) == (1, 2)
    assert (proposal.basis, proposal.proposed_by, proposal.confirmed_at) == (BASIS, curator, None)
    event = AuditEvent.objects.get(event_type="strain_risk_group_lower_proposed")
    assert (event.reason, event.strain_id, event.actor_id) == (LOWER, group2.public_id, curator.pk)
    assert event.changes == {
        "risk_group_proposal": [
            None,
            {
                "public_id": str(proposal.public_id),
                "risk_group": 1,
                "from_risk_group": 2,
                "basis": BASIS,
                "basis_entry": None,
            },
        ]
    }


@pytest.mark.rule("R-RISK-06")
def test_another_manager_confirms_and_the_group_drops_with_both_people(
    curator: User, manager: User, group2: Strain
) -> None:
    proposal = propose(curator, group2)
    lowered = confirm(manager, group2, proposal.public_id)
    proposal.refresh_from_db()
    assert (lowered.risk_group, lowered.risk_group_basis) == (1, BASIS)
    assert lowered.risk_group_set_at == proposal.confirmed_at
    assert proposal.confirmed_by == manager
    event = AuditEvent.objects.get(event_type="strain_risk_group_changed")
    assert (event.actor_id, event.reason) == (manager.pk, LOWER)
    assert event.changes["risk_group"] == [2, 1]
    assert event.changes["basis"] == [ACCESSION_BASIS, BASIS]
    assert event.changes["basis_entry"] == [None, None]
    assert event.changes["risk_group_proposal"] == [None, str(proposal.public_id)]
    assert event.changes["proposed_by"] == [None, str(curator.public_id)]
    assert event.changes["confirmed_by"] == [None, str(manager.public_id)]
    confirmed_at = proposal.confirmed_at
    assert confirmed_at is not None
    assert event.changes["proposed_at"] == [None, proposal.proposed_at.isoformat()]
    assert event.changes["confirmed_at"] == [None, confirmed_at.isoformat()]
    labels = set(RowChange.objects.values_list("table_label", flat=True))
    assert {"strains.riskgroupproposal", "strains.strain"} <= labels


def test_two_managers_may_lower_one_together(manager: User, lab: Lab, group2: Strain) -> None:
    second = member_of(lab, Role.MANAGER, "second-manager")
    confirm(second, group2, propose(manager, group2).public_id)
    assert Strain.objects.get(pk=group2.pk).risk_group == 1


@pytest.mark.rule("R-RISK-06")
def test_the_events_of_a_lowering_hold_no_personal_value(
    curator: User, manager: User, group2: Strain
) -> None:
    """ADR 0005: an event names people by their public id, never by a name, a username or an
    address."""
    confirm(manager, group2, propose(curator, group2).public_id)
    written = [str(event.changes) + event.reason for event in AuditEvent.objects.all()]
    personal = [
        value
        for value in (curator.username, manager.username, curator.email, manager.email)
        if value
    ]
    assert len(personal) >= 2  # the people really have names to leak
    for text in written:
        for value in personal:
            assert value not in text, text
    changed = str(AuditEvent.objects.get(event_type="strain_risk_group_changed").changes)
    assert str(curator.public_id) in changed and str(manager.public_id) in changed


# Who may.


@pytest.mark.rule("R-RISK-06")
def test_nobody_confirms_their_own_proposal(manager: User, group2: Strain) -> None:
    proposal = propose(manager, group2)
    refused(
        services.ConfirmOwnRiskGroup,
        "confirm_own_risk_group",
        lambda: confirm(manager, group2, proposal.public_id),
    )
    assert Strain.objects.get(pk=group2.pk).risk_group == 2


@pytest.mark.rule("R-RISK-06")
@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_only_a_manager_confirms(
    role: Role, team: dict[Role, User], lab: Lab, group2: Strain
) -> None:
    proposal = propose(member_of(lab, Role.CURATOR, "proposer"), group2)
    refused(Forbidden, "permission_denied", lambda: confirm(team[role], group2, proposal.public_id))
    assert not role_has(role, Perm.CONFIRM_RISK_GROUP)
    assert role_has(Role.MANAGER, Perm.CONFIRM_RISK_GROUP)


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN])
def test_a_viewer_or_technician_neither_proposes_nor_withdraws(
    role: Role, team: dict[Role, User], curator: User, group2: Strain
) -> None:
    refused(Forbidden, "permission_denied", lambda: propose(team[role], group2))
    proposal = propose(curator, group2)
    refused(
        Forbidden, "permission_denied", lambda: withdraw(team[role], group2, proposal.public_id)
    )


@pytest.mark.rule("R-RISK-06")
def test_a_manager_demoted_after_reading_does_not_confirm(
    curator: User, manager: User, group2: Strain
) -> None:
    """The role is read again under the lab lock, not taken from the request's access."""
    proposal = propose(curator, group2)
    access = access_for(manager)
    Membership.objects.filter(user=manager).update(role=Role.CURATOR)
    with as_(manager), pytest.raises(Forbidden) as raised:
        services.strain_risk_group_lower_confirm(
            access=access, strain=group2, proposal=proposal.public_id
        )
    assert raised.value.code == "permission_denied"
    assert Strain.objects.get(pk=group2.pk).risk_group == 2


# What may be proposed, and what one person still does.


@pytest.mark.rule("R-RISK-08")
def test_a_raise_stays_one_step_and_needs_no_second_person(
    curator: User, make_strain: MakeStrain
) -> None:
    """A raise only tightens the rules, so one person who manages strains makes it; it goes one
    step at a time, so nobody jumps a group without stating the basis of each step (our own
    rule, no law read asks it)."""
    strain = make_strain()  # risk group 1
    error = refused(
        services.RiskGroupStepTooBig,
        "risk_group_step_too_big",
        lambda: raise_group(curator, strain, 3),
    )
    assert (error.status_code, error.attr) == (400, "risk_group")
    assert raise_group(curator, strain, 2).risk_group == 2
    assert raise_group(curator, strain, 3).risk_group == 3
    assert not RiskGroupProposal.objects.exists()


@pytest.mark.rule("R-RISK-02")
def test_a_proposal_to_group_4_is_refused_before_anything_is_written(
    curator: User, group2: Strain
) -> None:
    refused(
        services.RiskGroupRefused,
        "risk_group_4_refused",
        lambda: propose(curator, group2, group=4),
    )


def test_a_raise_and_the_same_group_are_not_proposed(curator: User, group2: Strain) -> None:
    refused(services.RiskGroupNotLower, "risk_group_not_lower", lambda: propose(curator, group2, 3))
    refused(services.RiskGroupNotLower, "risk_group_not_lower", lambda: propose(curator, group2, 2))


@pytest.mark.rule("R-RISK-07")
def test_a_proposal_without_a_basis_or_a_reason_is_refused(curator: User, group2: Strain) -> None:
    refused(RuleViolation, "basis_required", lambda: propose(curator, group2, basis="   "))
    with as_(curator):
        refused(
            RuleViolation,
            "reason_required",
            lambda: services.strain_risk_group_lower_propose(
                access=access_for(curator), strain=group2, risk_group=1, basis=BASIS, reason=" "
            ),
        )


# One open proposal, and the one the manager read.


def test_one_open_proposal_per_strain(curator: User, manager: User, group2: Strain) -> None:
    propose(curator, group2)
    refused(services.RiskGroupProposed, "risk_group_proposed", lambda: propose(manager, group2))


def test_the_confirmation_names_the_open_proposal(
    curator: User, manager: User, group2: Strain
) -> None:
    refused(
        services.RiskGroupNotProposed,
        "risk_group_not_proposed",
        lambda: confirm(manager, group2, uuid4()),
    )
    read = propose(curator, group2)
    withdraw(curator, group2, read.public_id)
    refused(
        services.RiskGroupNotProposed,
        "risk_group_not_proposed",
        lambda: confirm(manager, group2, read.public_id),
    )
    propose(curator, group2)
    refused(
        services.RiskGroupProposalChanged,
        "risk_group_proposal_changed",
        lambda: confirm(manager, group2, read.public_id),
    )


@pytest.mark.rule("R-RISK-06")
def test_a_proposal_is_withdrawn_with_a_reason_and_another_may_follow(
    curator: User, manager: User, group2: Strain
) -> None:
    first = propose(curator, group2)
    withdraw(manager, group2, first.public_id)
    first.refresh_from_db()
    assert (first.withdrawn_by, first.withdraw_reason) == (manager, "Listed after all.")
    group2.refresh_from_db()
    assert (group2.risk_group, group2.risk_group_basis) == (2, ACCESSION_BASIS)
    event = AuditEvent.objects.get(event_type="strain_risk_group_lower_withdrawn")
    assert (event.reason, event.changes) == (
        "Listed after all.",
        {"risk_group_proposal": [str(first.public_id), None]},
    )
    second = propose(curator, group2)
    confirm(manager, group2, second.public_id)
    assert list(group2.risk_group_proposals.order_by("pk").values_list("pk", flat=True)) == [
        first.pk,
        second.pk,
    ]
    refused(RuleViolation, "reason_required", lambda: withdraw(curator, group2, uuid4(), " "))


def test_a_withdrawal_names_the_open_proposal(curator: User, group2: Strain) -> None:
    refused(
        services.RiskGroupNotProposed,
        "risk_group_not_proposed",
        lambda: withdraw(curator, group2, uuid4()),
    )


def test_a_proposal_read_against_another_group_is_not_confirmed(
    curator: User, manager: User, group2: Strain
) -> None:
    """The basis was read against the group the proposal names: a group changed meanwhile makes
    it outdated, not applied."""
    proposal = propose(curator, group2)
    raise_group(curator, group2, 3)
    refused(
        services.RiskGroupProposalOutdated,
        "risk_group_proposal_outdated",
        lambda: confirm(manager, group2, proposal.public_id),
    )
    assert Strain.objects.get(pk=group2.pk).risk_group == 3


def test_a_strain_can_be_lowered_again_later(
    curator: User, manager: User, make_strain: MakeStrain
) -> None:
    strain = make_strain(risk_group=3)
    confirm(manager, strain, propose(curator, strain, 2).public_id)
    confirm(manager, strain, propose(curator, strain, 1).public_id)
    strain.refresh_from_db()
    assert strain.risk_group == 1
    assert RiskGroupProposal.objects.filter(confirmed_at__isnull=False).count() == 2


# What else reads the risk group: the lower one counts only after the confirmation.


@pytest.mark.rule("R-RISK-06")
def test_the_shipment_rule_and_the_detail_read_the_higher_group_while_it_waits(
    curator: User, group2: Strain
) -> None:
    """distribution.services.shipment counts a strain of group 2 or higher as a pathogen
    (R-SHIP-03) and distribution.policy asks the requester's containment to reach the group
    (R-DIST-10); both read strains_strain.risk_group, which a proposal leaves alone."""
    propose(curator, group2)
    assert Strain.objects.get(pk=group2.pk).risk_group == 2
    body = logged_in(curator).get(f"{STRAINS_URL}{group2.public_id}/").json()
    assert body["risk_group"] == 2
    assert body["risk_group_proposal"]["risk_group"] == 1
    assert body["risk_group_basis"] == ACCESSION_BASIS


# The API.


def risk_url(strain: Strain, tail: str = "") -> str:
    return f"{STRAINS_URL}{strain.public_id}/risk-group-proposal/{tail}"


def test_the_api_offers_the_confirmation_to_the_managers_who_may_give_it(
    curator: User, manager: User, viewer: User, group2: Strain
) -> None:
    def proposal_as(user: User) -> Any:
        return (
            logged_in(user).get(f"{STRAINS_URL}{group2.public_id}/").json()["risk_group_proposal"]
        )

    response = logged_in(curator).post(
        risk_url(group2),
        {"risk_group": 1, "basis": BASIS, "reason": LOWER},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    shown = response.json()["risk_group_proposal"]
    assert shown["confirm_refusal"] == "confirm_own_risk_group"
    assert (shown["risk_group"], shown["from_risk_group"], shown["basis"]) == (1, 2, BASIS)
    assert shown["basis_entry"] is None  # #169: this basis rests on no entry of the annex
    assert proposal_as(manager)["confirm_refusal"] is None
    assert proposal_as(viewer) == {**shown, "confirm_refusal": None}  # names nobody
    assert_problem(
        logged_in(curator).post(
            risk_url(group2, "confirm/"),
            {"proposal": shown["public_id"]},
            content_type="application/json",
        ),
        403,
        "permission_denied",
    )
    response = logged_in(manager).post(
        risk_url(group2, "confirm/"),
        {"proposal": shown["public_id"]},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["risk_group"], body["risk_group_basis"], body["risk_group_proposal"]) == (
        1,
        BASIS,
        None,
    )


def test_the_one_step_lowering_is_refused_by_the_api(curator: User, group2: Strain) -> None:
    response = logged_in(curator).post(
        f"{STRAINS_URL}{group2.public_id}/risk-group/",
        {"risk_group": 1, "basis": BASIS, "reason": LOWER},
        content_type="application/json",
    )
    assert_problem(response, 422, "risk_group_second_person_required")
    assert Strain.objects.get(pk=group2.pk).risk_group == 2


def test_the_api_asks_for_a_basis_a_reason_and_a_group(curator: User, group2: Strain) -> None:
    for body in (
        {},
        {"risk_group": 1, "reason": LOWER},
        {"risk_group": 1, "basis": "", "reason": LOWER},
        {"risk_group": 1, "basis": BASIS},
        {"risk_group": 1, "basis": "x" * 2001, "reason": LOWER},
    ):
        response = logged_in(curator).post(risk_url(group2), body, content_type="application/json")
        assert response.status_code == 400, response.content
    assert not RiskGroupProposal.objects.exists()


# The database, against every writer (migrations 0011 to 0014).


def guarded(message: str) -> Any:
    return pytest.raises((IntegrityError, InternalError), match=message)


def raw_proposal(strain: Strain, by: User, **fields: Any) -> RiskGroupProposal:
    values: dict[str, Any] = {
        "risk_group": 1,
        "from_risk_group": strain.risk_group,
        "basis": BASIS,
        "reason": LOWER,
        "proposed_at": timezone.now(),
        **fields,
    }
    return RiskGroupProposal.objects.create(
        lab_id=strain.lab_id, strain=strain, proposed_by=by, **values
    )


@pytest.mark.rule("R-RISK-06")
def test_a_lower_group_is_set_only_at_a_confirmed_proposal(
    curator: User, manager: User, group2: Strain
) -> None:
    now = timezone.now()
    lowered = {"risk_group": 1, "risk_group_basis": BASIS, "risk_group_set_at": now}
    with guarded("a second person confirms a proposal"), transaction.atomic():
        Strain.objects.filter(pk=group2.pk).update(**lowered)
    open_one = raw_proposal(group2, curator, proposed_at=now)
    with guarded("a second person confirms a proposal"), transaction.atomic():
        Strain.objects.filter(pk=group2.pk).update(**lowered)
    RiskGroupProposal.objects.filter(pk=open_one.pk).update(confirmed_by=manager, confirmed_at=now)
    # Another basis, another time or another group than the confirmation's is not what was
    # confirmed.
    for change in (
        {"risk_group_basis": "Something else."},
        {"risk_group_set_at": now + timedelta(seconds=1)},
    ):
        with guarded("a second person confirms a proposal"), transaction.atomic():
            Strain.objects.filter(pk=group2.pk).update(**(lowered | change))
    Strain.objects.filter(pk=group2.pk).update(**lowered)
    assert Strain.objects.get(pk=group2.pk).risk_group == 1


@pytest.mark.rule("R-RISK-07")
def test_the_database_asks_every_change_for_its_basis_and_its_time(group2: Strain) -> None:
    """The strain comes out of its accession with a basis (#169), so a change that drops it, or
    gives words without a time, is refused as a change that never had one is."""
    for change in (
        {"risk_group_basis": "", "risk_group_set_at": None},
        {"risk_group_basis": "   ", "risk_group_set_at": None},
        {"risk_group_basis": BASIS, "risk_group_set_at": None},
    ):
        with guarded("states its basis and the time"), transaction.atomic():
            Strain.objects.filter(pk=group2.pk).update(risk_group=3, **change)
    with guarded("changes with the group"), transaction.atomic():
        Strain.objects.filter(pk=group2.pk).update(risk_group_basis=BASIS)
    Strain.objects.filter(pk=group2.pk).update(
        risk_group=3, risk_group_basis=BASIS, risk_group_set_at=timezone.now()
    )


@pytest.mark.rule("R-RISK-08")
def test_the_database_lets_a_group_rise_one_step_at_a_time(group2: Strain) -> None:
    with guarded("rises one step at a time"), transaction.atomic():
        Strain.objects.filter(pk=group2.pk).update(
            risk_group=4, risk_group_basis=BASIS, risk_group_set_at=timezone.now()
        )
    Strain.objects.filter(pk=group2.pk).update(
        risk_group=3, risk_group_basis=BASIS, risk_group_set_at=timezone.now()
    )


@pytest.mark.rule("R-RISK-06")
def test_a_confirmed_proposal_is_not_applied_twice(
    curator: User, manager: User, group2: Strain
) -> None:
    """A group raised again after a lowering cannot be lowered once more on the same confirmed
    proposal: the time of a change is later than the one before it."""
    proposal = propose(curator, group2)
    confirm(manager, group2, proposal.public_id)
    proposal.refresh_from_db()
    raise_group(curator, group2, 2)
    with guarded("later than the one before it"), transaction.atomic():
        Strain.objects.filter(pk=group2.pk).update(
            risk_group=1, risk_group_basis=BASIS, risk_group_set_at=proposal.confirmed_at
        )
    assert Strain.objects.get(pk=group2.pk).risk_group == 2


def test_the_proposer_never_confirms_in_the_database_either(curator: User, group2: Strain) -> None:
    proposal = raw_proposal(group2, curator)
    with (
        pytest.raises(IntegrityError, match="strains_riskgroupproposal_second_person"),
        transaction.atomic(),
    ):
        RiskGroupProposal.objects.filter(pk=proposal.pk).update(
            confirmed_by=curator, confirmed_at=timezone.now()
        )


def test_a_proposal_is_settled_once_and_never_deleted(
    curator: User, manager: User, group2: Strain
) -> None:
    proposal = raw_proposal(group2, curator)
    with guarded("changes once"), transaction.atomic():
        RiskGroupProposal.objects.filter(pk=proposal.pk).update(basis="Other.")
    RiskGroupProposal.objects.filter(pk=proposal.pk).update(
        withdrawn_by=manager, withdrawn_at=timezone.now(), withdraw_reason="Listed."
    )
    with guarded("changes once"), transaction.atomic():
        RiskGroupProposal.objects.filter(pk=proposal.pk).update(withdraw_reason="Other.")
    with guarded("never deleted"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM strains_riskgroupproposal WHERE id = %s", [proposal.pk])


def test_a_proposal_is_made_open_to_lower_the_group_the_strain_has(
    curator: User, manager: User, other_lab: Lab, group2: Strain
) -> None:
    with guarded("a proposal is made open"), transaction.atomic():
        raw_proposal(group2, curator, confirmed_by=manager, confirmed_at=timezone.now())
    with guarded("a proposal is made open"), transaction.atomic():
        raw_proposal(group2, curator, from_risk_group=3)
    with guarded("a proposal is made open"), transaction.atomic():
        RiskGroupProposal.objects.create(
            lab=other_lab,
            strain=group2,
            risk_group=1,
            from_risk_group=2,
            basis=BASIS,
            reason=LOWER,
            proposed_by=curator,
            proposed_at=timezone.now(),
        )
    with guarded("strains_riskgroupproposal_lowers"), transaction.atomic():
        raw_proposal(group2, curator, risk_group=2)


def test_the_runtime_role_works_the_two_steps_and_cannot_skip_them(
    as_curator: AuditContext,
    curator: User,
    manager: User,
    group2: Strain,
    runtime_role: CursorWrapper,
) -> None:
    # clock_timestamp(), not now(): now() is the transaction's start, which is before the
    # accession recorded its own basis in this same transaction (#169), and the guard would
    # refuse a change that is not later than the one before it instead of the rule under test.
    refused_sql(
        runtime_role,
        "UPDATE strains_strain SET risk_group = 1, risk_group_basis = 'x',"  # noqa: S608
        f" risk_group_set_at = clock_timestamp() WHERE id = {group2.pk}",
        "a second person confirms a proposal",
    )
    proposal = propose(curator, group2)
    refused_sql(
        runtime_role,
        "DELETE FROM strains_riskgroupproposal",
        "permission denied for table strains_riskgroupproposal",
    )
    confirm(manager, group2, proposal.public_id)
    assert Strain.objects.get(pk=group2.pk).risk_group == 1


# A confirmed proposal holds its outcome, at commit (migration 0014, as #151 did for the others).

NOT_LOWERED = "a confirmed proposal lowers its strain"


@pytest.mark.rule("R-RISK-06")
def test_the_runtime_role_cannot_confirm_a_lowering_that_did_not_happen(
    as_curator: AuditContext,
    curator: User,
    manager: User,
    group2: Strain,
    runtime_role: CursorWrapper,
) -> None:
    proposal = propose(curator, group2)
    now = timezone.now()
    confirm_sql = (
        "UPDATE strains_riskgroupproposal SET confirmed_at = %s,"  # noqa: S608
        f" confirmed_by_id = {manager.pk} WHERE id = {proposal.pk}"
    )
    with refused_at_commit(NOT_LOWERED):
        runtime_role.execute(confirm_sql, [now])
    proposal.refresh_from_db()
    assert proposal.confirmed_at is None
    with at_commit():  # both in one transaction, as the service writes them
        runtime_role.execute(confirm_sql, [now])
        runtime_role.execute(
            "UPDATE strains_strain SET risk_group = %s, risk_group_basis = %s,"  # noqa: S608
            f" risk_group_set_at = %s WHERE id = {group2.pk}",
            [proposal.risk_group, proposal.basis, now],
        )
    assert Strain.objects.get(pk=group2.pk).risk_group == 1

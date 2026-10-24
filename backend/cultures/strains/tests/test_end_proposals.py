"""A restriction ends in two steps, by two people (#105, ADR 0009).

One person who manages strains proposes it, with the reason; a manager other than the proposer
confirms it, which ends the restriction with that reason. Until then the strain stays regulated
for every rule that reads the active restrictions, so nobody lets a strain out of its rules
alone. The database holds it against every writer: a restriction ends only at the confirmation
of a proposal, and the proposer never confirms.
"""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from django.db import IntegrityError, InternalError, connection, transaction
from django.db.backends.utils import CursorWrapper
from django.utils import timezone

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel, RowChange
from cultures.audit.tests.conftest import refused as refused_sql
from cultures.biosafety.models import AuthorisationKind
from cultures.core.exceptions import DomainError, Forbidden, RuleViolation
from cultures.core.testing import assert_problem, logged_in
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.strains import selectors, services
from cultures.strains.models import RestrictionEndProposal, Strain, StrainRestriction
from cultures.users.models import User

from .conftest import GMO, STRAINS_URL, VRAT, MakeStrain, make_permit

pytestmark = pytest.mark.django_db


def as_(user: User) -> Any:
    return audit_context(channel=Channel.API, actor=user, request_id="req-end")


def propose(user: User, restriction: StrainRestriction, reason: str = "Delisted.") -> Any:
    with as_(user):
        return services.strain_restriction_end_propose(
            access=access_for(user), restriction=restriction, reason=reason
        )


def confirm(user: User, restriction: StrainRestriction, proposal: Any) -> StrainRestriction:
    with as_(user):
        return services.strain_restriction_end_confirm(
            access=access_for(user), restriction=restriction, proposal=proposal
        )


def withdraw(user: User, restriction: StrainRestriction, proposal: Any) -> Any:
    with as_(user):
        return services.strain_restriction_end_withdraw(
            access=access_for(user), restriction=restriction, proposal=proposal, reason="Listed."
        )


def snapshot() -> tuple[Any, ...]:
    rows = tuple(
        list(m._default_manager.order_by("pk").values())
        for m in (StrainRestriction, RestrictionEndProposal)
    )
    return (*rows, AuditEvent.objects.count(), RowChange.objects.count())


def refused(error: type[DomainError], code: str, call: Callable[[], object]) -> None:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert raised.value.code == code
    assert snapshot() == before


@pytest.fixture
def gmo(make_strain: MakeStrain) -> StrainRestriction:
    return StrainRestriction.objects.get(strain=make_strain(restrictions=[GMO]))


def regulated(strain: Strain) -> bool:
    return selectors.regulating_restrictions().filter(strain=strain).exists()


# The two steps.


def test_a_proposal_changes_nothing_for_the_strain(curator: User, gmo: StrainRestriction) -> None:
    proposal = propose(curator, gmo, "  The annex no longer lists it.  ")
    gmo.refresh_from_db()
    assert (gmo.ended_at, gmo.end_reason) == (None, "")
    assert regulated(gmo.strain)  # masked, a manager's approval, two steps at shipment: as before
    assert (proposal.reason, proposal.proposed_by, proposal.confirmed_at) == (
        "The annex no longer lists it.",
        curator,
        None,
    )
    event = AuditEvent.objects.get(event_type="strain_restriction_end_proposed")
    assert (event.reason, event.strain_id, event.actor_id) == (
        "The annex no longer lists it.",
        gmo.strain.public_id,
        curator.pk,
    )
    assert event.changes == {
        "end_proposal": [
            None,
            {"public_id": str(proposal.public_id), "restriction": str(gmo.public_id)},
        ]
    }


def test_another_manager_confirms_and_the_restriction_ends_with_both_people(
    curator: User, manager: User, gmo: StrainRestriction
) -> None:
    proposal = propose(curator, gmo, "The annex no longer lists it.")
    ended = confirm(manager, gmo, proposal.public_id)
    proposal.refresh_from_db()
    assert ended.ended_at == proposal.confirmed_at
    assert ended.end_reason == "The annex no longer lists it."
    assert proposal.confirmed_by == manager
    assert not regulated(gmo.strain)
    event = AuditEvent.objects.get(event_type="strain_restriction_ended")
    assert (event.actor_id, event.reason) == (manager.pk, "The annex no longer lists it.")
    assert event.changes["proposed_by"] == [None, str(curator.public_id)]
    assert event.changes["confirmed_by"] == [None, str(manager.public_id)]
    assert event.changes["proposed_at"] == [None, proposal.proposed_at.isoformat()]
    assert event.changes["confirmed_at"] == [None, proposal.confirmed_at.isoformat()]
    assert event.changes["end_proposal"] == [None, str(proposal.public_id)]
    labels = set(RowChange.objects.values_list("table_label", flat=True))
    assert {"strains.restrictionendproposal", "strains.strainrestriction"} <= labels


def test_two_managers_may_end_one_together(manager: User, lab: Lab, gmo: StrainRestriction) -> None:
    second = member_of(lab, Role.MANAGER, "second-manager")
    confirm(second, gmo, propose(manager, gmo).public_id)
    gmo.refresh_from_db()
    assert gmo.ended_at is not None


# Who may.


def test_nobody_confirms_their_own_proposal(manager: User, gmo: StrainRestriction) -> None:
    proposal = propose(manager, gmo)
    refused(
        services.ConfirmOwnEndProposal,
        "confirm_own_end_proposal",
        lambda: confirm(manager, gmo, proposal.public_id),
    )


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_only_a_manager_confirms(
    role: Role, team: dict[Role, User], lab: Lab, gmo: StrainRestriction
) -> None:
    proposal = propose(member_of(lab, Role.CURATOR, "proposer"), gmo)
    refused(Forbidden, "permission_denied", lambda: confirm(team[role], gmo, proposal.public_id))


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN])
def test_a_viewer_or_technician_neither_proposes_nor_withdraws(
    role: Role, team: dict[Role, User], curator: User, gmo: StrainRestriction
) -> None:
    refused(Forbidden, "permission_denied", lambda: propose(team[role], gmo))
    proposal = propose(curator, gmo)
    refused(Forbidden, "permission_denied", lambda: withdraw(team[role], gmo, proposal.public_id))


def test_a_manager_demoted_after_reading_does_not_confirm(
    curator: User, manager: User, gmo: StrainRestriction
) -> None:
    """The role is read again under the lab lock, not taken from the request's access."""
    proposal = propose(curator, gmo)
    access = access_for(manager)
    Membership.objects.filter(user=manager).update(role=Role.CURATOR)
    with as_(manager), pytest.raises(Forbidden):
        services.strain_restriction_end_confirm(
            access=access, restriction=gmo, proposal=proposal.public_id
        )


# One open proposal, and the one the manager read.


def test_one_open_proposal_per_restriction(
    curator: User, manager: User, gmo: StrainRestriction
) -> None:
    propose(curator, gmo)
    refused(services.EndProposed, "end_proposed", lambda: propose(manager, gmo))


def test_the_confirmation_names_the_open_proposal(
    curator: User, manager: User, gmo: StrainRestriction
) -> None:
    refused(services.EndNotProposed, "end_not_proposed", lambda: confirm(manager, gmo, uuid4()))
    read = propose(curator, gmo)
    withdraw(curator, gmo, read.public_id)
    refused(
        services.EndNotProposed, "end_not_proposed", lambda: confirm(manager, gmo, read.public_id)
    )
    propose(curator, gmo, "Another reason.")
    refused(
        services.EndProposalChanged,
        "end_proposal_changed",
        lambda: confirm(manager, gmo, read.public_id),
    )


def test_a_withdrawn_proposal_stays_and_another_may_follow(
    curator: User, manager: User, gmo: StrainRestriction
) -> None:
    first = propose(curator, gmo)
    withdraw(manager, gmo, first.public_id)
    first.refresh_from_db()
    assert (first.withdrawn_by, first.withdraw_reason) == (manager, "Listed.")
    gmo.refresh_from_db()
    assert gmo.ended_at is None
    event = AuditEvent.objects.get(event_type="strain_restriction_end_withdrawn")
    assert (event.reason, event.changes) == (
        "Listed.",
        {"end_proposal": [str(first.public_id), None]},
    )
    second = propose(curator, gmo)
    confirm(manager, gmo, second.public_id)
    assert list(gmo.end_proposals.order_by("pk").values_list("pk", flat=True)) == [
        first.pk,
        second.pk,
    ]


def test_a_blank_reason_is_refused_before_anything_is_written(
    curator: User, gmo: StrainRestriction
) -> None:
    refused(RuleViolation, "reason_required", lambda: propose(curator, gmo, "   "))
    proposal = propose(curator, gmo)
    with as_(curator):
        refused(
            RuleViolation,
            "reason_required",
            lambda: services.strain_restriction_end_withdraw(
                access=access_for(curator), restriction=gmo, proposal=proposal.public_id, reason=" "
            ),
        )


def test_an_ended_restriction_takes_no_proposal(
    curator: User, manager: User, gmo: StrainRestriction
) -> None:
    confirm(manager, gmo, propose(curator, gmo).public_id)
    refused(services.RestrictionEnded, "restriction_ended", lambda: propose(curator, gmo))


# The window of the review: one curator alone could end a VRAT, approve and ship it unregulated.


def test_a_curator_alone_no_longer_lets_a_vrat_out_of_its_rules(
    lab: Lab, curator: User, make_strain: MakeStrain
) -> None:
    make_permit(lab, AuthorisationKind.CZ_VRAT)
    strain = make_strain(restrictions=[VRAT])
    vrat = StrainRestriction.objects.get(strain=strain)
    proposal = propose(curator, vrat)
    refused(Forbidden, "permission_denied", lambda: confirm(curator, vrat, proposal.public_id))
    assert regulated(strain)


# The API.


def end_url(restriction: StrainRestriction, tail: str = "") -> str:
    return (
        f"{STRAINS_URL}{restriction.strain.public_id}/restrictions/"
        f"{restriction.public_id}/end-proposal/{tail}"
    )


def test_the_api_offers_the_confirmation_to_the_managers_who_may_give_it(
    curator: User, manager: User, viewer: User, gmo: StrainRestriction
) -> None:
    def proposal_as(user: User) -> Any:
        body = logged_in(user).get(f"{STRAINS_URL}{gmo.strain.public_id}/").json()
        return body["restriction_history"][0]["end_proposal"]

    response = logged_in(curator).post(
        end_url(gmo), {"reason": "Delisted."}, content_type="application/json"
    )
    assert response.status_code == 200, response.content
    shown = response.json()["restriction_history"][0]["end_proposal"]
    assert shown["confirm_refusal"] == "confirm_own_end_proposal"
    assert proposal_as(manager)["confirm_refusal"] is None
    assert proposal_as(viewer) == {**shown, "confirm_refusal": None}  # names nobody
    assert_problem(
        logged_in(curator).post(
            end_url(gmo, "confirm/"),
            {"proposal": shown["public_id"]},
            content_type="application/json",
        ),
        403,
        "permission_denied",
    )
    response = logged_in(manager).post(
        end_url(gmo, "confirm/"), {"proposal": shown["public_id"]}, content_type="application/json"
    )
    assert response.status_code == 200, response.content
    ended = response.json()["restriction_history"][0]
    assert (ended["end_reason"], ended["end_proposal"]) == ("Delisted.", None)


def test_the_one_step_end_is_gone(curator: User, gmo: StrainRestriction) -> None:
    url = f"{STRAINS_URL}{gmo.strain.public_id}/restrictions/{gmo.public_id}/end/"
    response = logged_in(curator).post(url, {"reason": "x"}, content_type="application/json")
    assert response.status_code == 404
    assert StrainRestriction.objects.get(pk=gmo.pk).ended_at is None


def test_a_reason_is_needed_and_has_a_limit(curator: User, gmo: StrainRestriction) -> None:
    for body in ({}, {"reason": ""}, {"reason": "x" * 2001}):
        response = logged_in(curator).post(end_url(gmo), body, content_type="application/json")
        assert response.status_code == 400, response.content
    assert not gmo.end_proposals.exists()


# The database, against every writer (migration 0005).


def guarded(message: str) -> Any:
    return pytest.raises((IntegrityError, InternalError), match=message)


def raw_proposal(restriction: StrainRestriction, by: User, **fields: Any) -> RestrictionEndProposal:
    values = {"reason": "Delisted.", "proposed_at": timezone.now(), **fields}
    return RestrictionEndProposal.objects.create(
        lab_id=restriction.lab_id, restriction=restriction, proposed_by=by, **values
    )


def test_a_restriction_ends_only_at_a_confirmed_proposal(
    curator: User, manager: User, gmo: StrainRestriction
) -> None:
    now = timezone.now()
    with guarded("a second person confirms a proposal"), transaction.atomic():
        StrainRestriction.objects.filter(pk=gmo.pk).update(ended_at=now, end_reason="Delisted.")
    open_one = raw_proposal(gmo, curator, proposed_at=now)
    with guarded("a second person confirms a proposal"), transaction.atomic():
        StrainRestriction.objects.filter(pk=gmo.pk).update(ended_at=now, end_reason="Delisted.")
    RestrictionEndProposal.objects.filter(pk=open_one.pk).update(
        confirmed_by=manager, confirmed_at=now
    )
    # Another reason or another time than the confirmation's is not what was confirmed.
    for change in (
        {"ended_at": now, "end_reason": "Something else."},
        {"ended_at": timezone.now(), "end_reason": "Delisted."},
    ):
        with guarded("a second person confirms a proposal"), transaction.atomic():
            StrainRestriction.objects.filter(pk=gmo.pk).update(**change)
    StrainRestriction.objects.filter(pk=gmo.pk).update(ended_at=now, end_reason="Delisted.")


def test_the_proposer_never_confirms_in_the_database_either(
    curator: User, gmo: StrainRestriction
) -> None:
    proposal = raw_proposal(gmo, curator)
    with (
        pytest.raises(IntegrityError, match="strains_endproposal_second_person"),
        transaction.atomic(),
    ):
        RestrictionEndProposal.objects.filter(pk=proposal.pk).update(
            confirmed_by=curator, confirmed_at=timezone.now()
        )


def test_a_proposal_is_settled_once_and_never_deleted(
    curator: User, manager: User, gmo: StrainRestriction
) -> None:
    proposal = raw_proposal(gmo, curator)
    with guarded("changes once"), transaction.atomic():
        RestrictionEndProposal.objects.filter(pk=proposal.pk).update(reason="Other.")
    RestrictionEndProposal.objects.filter(pk=proposal.pk).update(
        withdrawn_by=manager, withdrawn_at=timezone.now(), withdraw_reason="Listed."
    )
    with guarded("changes once"), transaction.atomic():
        RestrictionEndProposal.objects.filter(pk=proposal.pk).update(withdraw_reason="Other.")
    with guarded("never deleted"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM strains_restrictionendproposal WHERE id = %s", [proposal.pk])


def test_a_proposal_is_made_open_for_an_active_restriction_of_its_lab(
    curator: User, manager: User, other_lab: Lab, gmo: StrainRestriction
) -> None:
    with guarded("a proposal is made open"), transaction.atomic():
        raw_proposal(gmo, curator, confirmed_by=manager, confirmed_at=timezone.now())
    with guarded("a proposal is made open"), transaction.atomic():
        RestrictionEndProposal.objects.create(
            lab=other_lab,
            restriction=gmo,
            reason="x",
            proposed_by=curator,
            proposed_at=timezone.now(),
        )
    confirm(manager, gmo, propose(curator, gmo).public_id)
    with guarded("a proposal is made open"), transaction.atomic():
        raw_proposal(gmo, curator)


def test_the_runtime_role_works_the_two_steps_and_cannot_skip_them(
    as_curator: AuditContext,
    curator: User,
    manager: User,
    gmo: StrainRestriction,
    runtime_role: CursorWrapper,
) -> None:
    refused_sql(
        runtime_role,
        f"UPDATE strains_strainrestriction SET ended_at = now(), end_reason = 'x'"  # noqa: S608
        f" WHERE id = {gmo.pk}",
        "a second person confirms a proposal",
    )
    proposal = propose(curator, gmo)
    refused_sql(
        runtime_role,
        "DELETE FROM strains_restrictionendproposal",
        "permission denied for table strains_restrictionendproposal",
    )
    confirm(manager, gmo, proposal.public_id)
    gmo.refresh_from_db()
    assert gmo.ended_at is not None

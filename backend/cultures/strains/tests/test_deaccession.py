"""A strain leaves the collection without losing its history (#20, ADR 0008 and 0009).

A strain that is not regulated is deaccessioned by one person who manages strains, with a cause
and a reason. A regulated one (an active restriction of any kind) leaves in two steps like the
end of a restriction (#105): someone who manages strains proposes it, a manager other than the
proposer confirms it, or it is withdrawn. A quarantine pest states its final use. Deaccessioned
is terminal: the row, its number and its history stay, and nothing of it changes. The database
holds the terminal state and the two people against every writer. What the deaccession does to
requests and vials is tested in distribution/tests/test_deaccession.py.
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
from cultures.biosafety.models import AuthorisationKind, RestrictionKind
from cultures.core.exceptions import DomainError, Forbidden, RuleViolation
from cultures.core.testing import assert_problem, logged_in
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.strains import selectors, services
from cultures.strains.models import (
    DeaccessionCause,
    FinalUse,
    Strain,
    StrainDeaccessionProposal,
    StrainRestriction,
    StrainStatus,
)
from cultures.strains.services import Deaccession, RestrictionInput
from cultures.users.models import User

from .conftest import (
    DUAL_USE,
    GMO,
    QUARANTINE,
    STRAINS_URL,
    VRAT,
    MakeStrain,
    end_restriction,
    make_permit,
)

pytestmark = pytest.mark.django_db

DEAD = Deaccession(DeaccessionCause.NON_VIABLE, "No growth after three revivals.")


def as_(user: User) -> Any:
    return audit_context(channel=Channel.API, actor=user, request_id="req-deaccession")


def leave(user: User, strain: Strain, data: Deaccession = DEAD) -> Strain:
    with as_(user):
        return services.strain_deaccession(access=access_for(user), strain=strain, data=data)


def propose(user: User, strain: Strain, data: Deaccession = DEAD) -> StrainDeaccessionProposal:
    with as_(user):
        return services.strain_deaccession_propose(
            access=access_for(user), strain=strain, data=data
        )


def confirm(user: User, strain: Strain, proposal: Any) -> Strain:
    with as_(user):
        return services.strain_deaccession_confirm(
            access=access_for(user), strain=strain, proposal=proposal
        )


def withdraw(user: User, strain: Strain, proposal: Any) -> StrainDeaccessionProposal:
    with as_(user):
        return services.strain_deaccession_withdraw(
            access=access_for(user), strain=strain, proposal=proposal, reason="It grew after all."
        )


def snapshot() -> tuple[Any, ...]:
    rows = tuple(
        list(m._default_manager.order_by("pk").values())
        for m in (Strain, StrainRestriction, StrainDeaccessionProposal)
    )
    return (*rows, AuditEvent.objects.count(), RowChange.objects.count())


def refused(error: type[DomainError], code: str, call: Callable[[], object]) -> None:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert raised.value.code == code
    assert snapshot() == before


@pytest.fixture
def gmo(make_strain: MakeStrain) -> Strain:
    """A regulated strain: an active GMO restriction (invented Testella exempli)."""
    return make_strain(restrictions=[GMO])


# One person, a strain that is not regulated.


def test_a_curator_deaccessions_a_strain_that_no_longer_grows(
    curator: User, make_strain: MakeStrain
) -> None:
    strain = make_strain()
    number = strain.accession_number
    left = leave(curator, strain, Deaccession(DeaccessionCause.NON_VIABLE, "  No growth.  "))
    left.refresh_from_db()
    assert left.status == StrainStatus.DEACCESSIONED
    assert (left.deaccession_cause, left.deaccession_reason, left.final_use) == (
        DeaccessionCause.NON_VIABLE,
        "No growth.",
        "",
    )
    assert left.deaccessioned_by == curator
    assert left.deaccessioned_at is not None
    assert left.accession_number == number  # the number stays with it
    event = AuditEvent.objects.get(event_type="strain_deaccessioned")
    assert (event.reason, event.strain_id, event.actor_id) == (
        "No growth.",
        strain.public_id,
        curator.pk,
    )
    assert event.changes == {
        "status": ["active", "deaccessioned"],
        "cause": [None, "non_viable"],
        "requests_cancelled": [None, []],
        "vials_to_destroy": [None, 0],
    }


def test_the_next_strain_gets_a_new_number(curator: User, make_strain: MakeStrain) -> None:
    first = make_strain()
    leave(curator, first)
    second = make_strain(name_as_received="Testella exempli T2")
    assert first.accession_seq is not None and second.accession_seq is not None
    assert second.accession_seq == first.accession_seq + 1


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN])
def test_below_curator_nobody_deaccessions(
    role: Role, team: dict[Role, User], make_strain: MakeStrain
) -> None:
    strain = make_strain()
    refused(Forbidden, "permission_denied", lambda: leave(team[role], strain))


def test_a_manager_deaccessions_too(manager: User, make_strain: MakeStrain) -> None:
    assert leave(manager, make_strain()).status == StrainStatus.DEACCESSIONED


def test_a_curator_demoted_after_reading_does_not_deaccession(
    curator: User, make_strain: MakeStrain
) -> None:
    """The role is read again under the lab lock, not taken from the request's access."""
    strain = make_strain()
    access = access_for(curator)
    Membership.objects.filter(user=curator).update(role=Role.TECHNICIAN)
    with as_(curator), pytest.raises(Forbidden):
        services.strain_deaccession(access=access, strain=strain, data=DEAD)


def test_a_reason_is_required_before_anything_is_written(
    curator: User, make_strain: MakeStrain
) -> None:
    strain = make_strain()
    refused(
        RuleViolation,
        "reason_required",
        lambda: leave(curator, strain, Deaccession(DeaccessionCause.LOST, "   ")),
    )


def test_deaccessioned_is_terminal(curator: User, manager: User, make_strain: MakeStrain) -> None:
    strain = make_strain()
    leave(curator, strain)
    refused(services.StrainDeaccessioned, "strain_deaccessioned", lambda: leave(manager, strain))
    for change in (
        lambda: services.strain_set_risk_group(
            access=access_for(curator), strain=strain, risk_group=2, reason="r"
        ),
        lambda: services.strain_restriction_add(
            access=access_for(curator), strain=strain, restriction=DUAL_USE, reason="r"
        ),
    ):
        with as_(curator):
            refused(services.StrainDeaccessioned, "strain_deaccessioned", change)


# A regulated strain: two people.


def test_one_person_does_not_deaccession_a_regulated_strain(curator: User, gmo: Strain) -> None:
    refused(
        services.DeaccessionNeedsSecondPerson,
        "second_person_required",
        lambda: leave(curator, gmo),
    )


def test_a_proposal_changes_nothing_for_the_strain(curator: User, gmo: Strain) -> None:
    proposal = propose(curator, gmo, Deaccession(DeaccessionCause.CONTAMINATED, " Mixed. "))
    gmo.refresh_from_db()
    assert gmo.status == StrainStatus.ACTIVE
    assert (proposal.cause, proposal.reason, proposal.proposed_by) == (
        DeaccessionCause.CONTAMINATED,
        "Mixed.",
        curator,
    )
    event = AuditEvent.objects.get(event_type="strain_deaccession_proposed")
    assert (event.reason, event.strain_id) == ("Mixed.", gmo.public_id)
    assert event.changes == {
        "deaccession_proposal": [
            None,
            {"public_id": str(proposal.public_id), "cause": "contaminated", "final_use": ""},
        ]
    }


def test_another_manager_confirms_and_the_strain_leaves_with_both_people(
    curator: User, manager: User, gmo: Strain
) -> None:
    proposal = propose(curator, gmo)
    left = confirm(manager, gmo, proposal.public_id)
    proposal.refresh_from_db()
    left.refresh_from_db()
    assert left.status == StrainStatus.DEACCESSIONED
    assert (left.deaccessioned_by, left.deaccessioned_at) == (manager, proposal.confirmed_at)
    assert (left.deaccession_cause, left.deaccession_reason) == (DEAD.cause, DEAD.reason)
    # The restriction stays: the vials are still there to be destroyed, and regulated.
    assert selectors.regulating_restrictions().filter(strain=gmo).exists()
    event = AuditEvent.objects.get(event_type="strain_deaccessioned")
    assert (event.actor_id, event.reason) == (manager.pk, DEAD.reason)
    assert event.changes["proposed_by"] == [None, str(curator.public_id)]
    assert event.changes["confirmed_by"] == [None, str(manager.public_id)]
    assert event.changes["proposed_at"] == [None, proposal.proposed_at.isoformat()]
    assert proposal.confirmed_at is not None
    assert event.changes["confirmed_at"] == [None, proposal.confirmed_at.isoformat()]
    assert event.changes["deaccession_proposal"] == [None, str(proposal.public_id)]


def test_nobody_confirms_their_own_proposal(manager: User, gmo: Strain) -> None:
    proposal = propose(manager, gmo)
    refused(
        services.ConfirmOwnDeaccession,
        "confirm_own_deaccession",
        lambda: confirm(manager, gmo, proposal.public_id),
    )


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_only_a_manager_confirms(role: Role, team: dict[Role, User], lab: Lab, gmo: Strain) -> None:
    proposal = propose(member_of(lab, Role.CURATOR, "proposer"), gmo)
    refused(Forbidden, "permission_denied", lambda: confirm(team[role], gmo, proposal.public_id))


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN])
def test_a_viewer_or_technician_neither_proposes_nor_withdraws(
    role: Role, team: dict[Role, User], curator: User, gmo: Strain
) -> None:
    refused(Forbidden, "permission_denied", lambda: propose(team[role], gmo))
    proposal = propose(curator, gmo)
    refused(Forbidden, "permission_denied", lambda: withdraw(team[role], gmo, proposal.public_id))


def test_a_strain_that_is_not_regulated_is_not_proposed(
    curator: User, make_strain: MakeStrain
) -> None:
    strain = make_strain()
    refused(
        services.DeaccessionInOneStep, "deaccession_in_one_step", lambda: propose(curator, strain)
    )


def test_one_open_proposal_per_strain(curator: User, manager: User, gmo: Strain) -> None:
    propose(curator, gmo)
    refused(services.DeaccessionProposed, "deaccession_proposed", lambda: propose(manager, gmo))


def test_the_confirmation_names_the_open_proposal(
    curator: User, manager: User, gmo: Strain
) -> None:
    refused(
        services.DeaccessionNotProposed,
        "deaccession_not_proposed",
        lambda: confirm(manager, gmo, uuid4()),
    )
    read = propose(curator, gmo)
    withdraw(curator, gmo, read.public_id)
    refused(
        services.DeaccessionNotProposed,
        "deaccession_not_proposed",
        lambda: confirm(manager, gmo, read.public_id),
    )
    propose(curator, gmo, Deaccession(DeaccessionCause.LOST, "Not in its box."))
    refused(
        services.DeaccessionProposalChanged,
        "deaccession_proposal_changed",
        lambda: confirm(manager, gmo, read.public_id),
    )


def test_a_withdrawn_proposal_stays_and_another_may_follow(
    curator: User, manager: User, gmo: Strain
) -> None:
    first = propose(curator, gmo)
    withdraw(manager, gmo, first.public_id)
    first.refresh_from_db()
    assert (first.withdrawn_by, first.withdraw_reason) == (manager, "It grew after all.")
    gmo.refresh_from_db()
    assert gmo.status == StrainStatus.ACTIVE
    event = AuditEvent.objects.get(event_type="strain_deaccession_withdrawn")
    assert (event.reason, event.changes) == (
        "It grew after all.",
        {"deaccession_proposal": [str(first.public_id), None]},
    )
    second = propose(curator, gmo)
    confirm(manager, gmo, second.public_id)
    assert list(gmo.deaccession_proposals.order_by("pk").values_list("pk", flat=True)) == [
        first.pk,
        second.pk,
    ]


def test_a_regulated_strain_whose_restriction_ended_leaves_in_one_step(
    curator: User, manager: User, gmo: Strain
) -> None:
    end_restriction(StrainRestriction.objects.get(strain=gmo), proposer=curator, confirmer=manager)
    assert leave(curator, gmo).status == StrainStatus.DEACCESSIONED


def test_an_open_proposal_is_settled_before_one_step(
    curator: User, manager: User, gmo: Strain
) -> None:
    """Proposed while regulated, the restriction ended since: one person does not go around the
    proposal; it is confirmed or withdrawn."""
    proposal = propose(curator, gmo)
    end_restriction(StrainRestriction.objects.get(strain=gmo), proposer=curator, confirmer=manager)
    refused(services.DeaccessionProposed, "deaccession_proposed", lambda: leave(curator, gmo))
    withdraw(curator, gmo, proposal.public_id)
    assert leave(curator, gmo).status == StrainStatus.DEACCESSIONED


def test_a_curator_alone_cannot_take_a_vrat_strain_out(
    lab: Lab, curator: User, make_strain: MakeStrain
) -> None:
    make_permit(lab, AuthorisationKind.CZ_VRAT)
    strain = make_strain(restrictions=[VRAT])
    refused(
        services.DeaccessionNeedsSecondPerson,
        "second_person_required",
        lambda: leave(curator, strain),
    )
    proposal = propose(curator, strain)
    refused(Forbidden, "permission_denied", lambda: confirm(curator, strain, proposal.public_id))


# The final use of a quarantine pest (Regulation (EU) 2019/829, Annex I (h)).


@pytest.fixture
def pest(lab: Lab, make_strain: MakeStrain) -> Strain:
    make_permit(lab, AuthorisationKind.QUARANTINE_PEST)
    return make_strain(restrictions=[QUARANTINE])


def test_a_quarantine_pest_states_its_final_use(curator: User, manager: User, pest: Strain) -> None:
    def missing() -> object:
        return propose(curator, pest)

    with pytest.raises(services.InvalidStrain) as raised:
        missing()
    assert (raised.value.code, raised.value.attr) == ("final_use_required", "final_use")
    proposal = propose(curator, pest, Deaccession(DEAD.cause, DEAD.reason, FinalUse.DESTRUCTION))
    left = confirm(manager, pest, proposal.public_id)
    left.refresh_from_db()
    assert left.final_use == FinalUse.DESTRUCTION
    event = AuditEvent.objects.get(event_type="strain_deaccessioned")
    assert event.changes["final_use"] == [None, "destruction"]


def test_only_a_quarantine_pest_states_a_final_use(curator: User, make_strain: MakeStrain) -> None:
    strain = make_strain()
    with pytest.raises(services.InvalidStrain) as raised:
        leave(curator, strain, Deaccession(DEAD.cause, DEAD.reason, FinalUse.STORAGE))
    assert (raised.value.code, raised.value.attr) == ("final_use_not_applicable", "final_use")


def test_a_proposal_whose_final_use_no_longer_fits_is_not_confirmed(
    curator: User, manager: User, pest: Strain
) -> None:
    proposal = propose(curator, pest, Deaccession(DEAD.cause, DEAD.reason, FinalUse.STORAGE))
    # A second restriction keeps the strain regulated while the quarantine one ends.
    with as_(curator):
        services.strain_restriction_add(
            access=access_for(curator), strain=pest, restriction=GMO, reason="Listed."
        )
    end_restriction(
        StrainRestriction.objects.get(strain=pest, kind=RestrictionKind.QUARANTINE_PEST),
        proposer=curator,
        confirmer=manager,
    )
    refused(
        services.DeaccessionProposalOutdated,
        "deaccession_proposal_outdated",
        lambda: confirm(manager, pest, proposal.public_id),
    )


# The list and the detail.


def test_the_list_hides_deaccessioned_strains_unless_asked(
    curator: User, viewer: User, make_strain: MakeStrain
) -> None:
    kept = make_strain(name_as_received="kept")
    gone = make_strain(name_as_received="gone")
    leave(curator, gone)

    def listed(**params: Any) -> list[str]:
        response = logged_in(viewer).get(STRAINS_URL, params)
        assert response.status_code == 200, response.content
        return [row["name_as_received"] for row in response.json()["results"]]

    assert listed() == ["kept"]
    assert listed(search=str(gone.accession_number)) == []
    assert listed(status="deaccessioned") == ["gone"]
    assert listed(status="active") == ["kept"]
    detail = logged_in(viewer).get(f"{STRAINS_URL}{gone.public_id}/")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "deaccessioned"
    assert body["deaccession"]["cause"] == "non_viable"
    assert body["deaccession"]["reason"] == DEAD.reason
    assert "deaccessioned_by" not in body["deaccession"]  # names nobody
    assert logged_in(viewer).get(f"{STRAINS_URL}{kept.public_id}/").json()["deaccession"] is None


def test_the_api_offers_the_confirmation_to_the_managers_who_may_give_it(
    curator: User, manager: User, viewer: User, gmo: Strain
) -> None:
    url = f"{STRAINS_URL}{gmo.public_id}/"
    body = {"cause": "contaminated", "reason": "Mixed culture."}
    assert_problem(
        logged_in(curator).post(f"{url}deaccession/", body, content_type="application/json"),
        422,
        "second_person_required",
    )
    response = logged_in(curator).post(
        f"{url}deaccession-proposal/", body, content_type="application/json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["regulated"] is True
    shown = response.json()["deaccession_proposal"]
    assert shown["confirm_refusal"] == "confirm_own_deaccession"
    assert logged_in(manager).get(url).json()["deaccession_proposal"]["confirm_refusal"] is None
    assert logged_in(viewer).get(url).json()["deaccession_proposal"] == {
        **shown,
        "confirm_refusal": None,
    }
    assert_problem(
        logged_in(curator).post(
            f"{url}deaccession-proposal/confirm/",
            {"proposal": shown["public_id"]},
            content_type="application/json",
        ),
        403,
        "permission_denied",
    )
    response = logged_in(manager).post(
        f"{url}deaccession-proposal/confirm/",
        {"proposal": shown["public_id"]},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    left = response.json()
    assert (left["status"], left["deaccession_proposal"]) == ("deaccessioned", None)
    assert left["deaccession"]["reason"] == "Mixed culture."


def test_the_input_is_checked(curator: User, make_strain: MakeStrain) -> None:
    strain = make_strain()
    url = f"{STRAINS_URL}{strain.public_id}/deaccession/"
    for body in (
        {},
        {"cause": "non_viable"},
        {"cause": "bored", "reason": "x"},
        {"cause": "non_viable", "reason": "x" * 2001},
        {"cause": "non_viable", "reason": "x", "final_use": "compost"},
    ):
        response = logged_in(curator).post(url, body, content_type="application/json")
        assert response.status_code == 400, (body, response.content)
    assert Strain.objects.get(pk=strain.pk).status == StrainStatus.ACTIVE


# The database, against every writer (migration 0009).


def guarded(message: str) -> Any:
    return pytest.raises((IntegrityError, InternalError), match=message)


def raw_leave(strain: Strain, by: User, **fields: Any) -> int:
    values = {
        "status": StrainStatus.DEACCESSIONED,
        "deaccessioned_at": timezone.now(),
        "deaccessioned_by": by,
        "deaccession_cause": DeaccessionCause.NON_VIABLE,
        "deaccession_reason": "No growth.",
        **fields,
    }
    return Strain.objects.filter(pk=strain.pk).update(**values)


def raw_proposal(strain: Strain, by: User, **fields: Any) -> StrainDeaccessionProposal:
    values = {
        "cause": DeaccessionCause.NON_VIABLE,
        "reason": "No growth.",
        "proposed_at": timezone.now(),
        **fields,
    }
    return StrainDeaccessionProposal.objects.create(
        lab_id=strain.lab_id, strain=strain, proposed_by=by, **values
    )


def test_the_database_refuses_a_one_person_deaccession_of_a_regulated_strain(
    curator: User, manager: User, gmo: Strain
) -> None:
    now = timezone.now()
    with guarded("a second person confirms a proposal"), transaction.atomic():
        raw_leave(gmo, curator, deaccessioned_at=now)
    open_one = raw_proposal(gmo, curator, proposed_at=now)
    with guarded("a second person confirms a proposal"), transaction.atomic():
        raw_leave(gmo, curator, deaccessioned_at=now)
    StrainDeaccessionProposal.objects.filter(pk=open_one.pk).update(
        confirmed_by=manager, confirmed_at=now
    )
    # Another person, time, cause or reason than the confirmation's is not what was confirmed.
    for change in (
        {"deaccessioned_by": curator, "deaccessioned_at": now},
        {"deaccessioned_by": manager, "deaccessioned_at": timezone.now()},
        {"deaccessioned_by": manager, "deaccessioned_at": now, "deaccession_cause": "lost"},
        {"deaccessioned_by": manager, "deaccessioned_at": now, "deaccession_reason": "Other."},
    ):
        with guarded("a second person confirms a proposal"), transaction.atomic():
            raw_leave(gmo, curator, **change)
    assert raw_leave(gmo, manager, deaccessioned_at=now) == 1


def test_the_proposer_never_confirms_in_the_database_either(curator: User, gmo: Strain) -> None:
    proposal = raw_proposal(gmo, curator)
    with (
        pytest.raises(IntegrityError, match="strains_deaccessionproposal_second_person"),
        transaction.atomic(),
    ):
        StrainDeaccessionProposal.objects.filter(pk=proposal.pk).update(
            confirmed_by=curator, confirmed_at=timezone.now()
        )


def test_the_database_holds_the_terminal_state(
    curator: User, manager: User, make_strain: MakeStrain
) -> None:
    strain = make_strain()
    assert raw_leave(strain, curator) == 1
    for change in (
        {"status": StrainStatus.ACTIVE},
        {"deaccession_reason": "Another story."},
        {"deaccession_cause": DeaccessionCause.LOST},
        {"deaccessioned_by": manager},
        {"deaccessioned_at": timezone.now()},
    ):
        with guarded("stays deaccessioned"), transaction.atomic():
            Strain.objects.filter(pk=strain.pk).update(**change)
    with guarded("never deleted"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM strains_strain WHERE id = %s", [strain.pk])


def test_the_facts_come_with_the_status_and_only_with_it(
    curator: User, make_strain: MakeStrain
) -> None:
    strain = make_strain()
    for missing in ("deaccessioned_at", "deaccessioned_by"):
        with (
            pytest.raises(IntegrityError, match="strains_strain_deaccession_iff_status"),
            transaction.atomic(),
        ):
            raw_leave(strain, curator, **{missing: None})
    for blank in ("deaccession_cause", "deaccession_reason"):
        with (
            pytest.raises(IntegrityError, match="strains_strain_deaccession_iff_status"),
            transaction.atomic(),
        ):
            raw_leave(strain, curator, **{blank: ""})
    with (
        pytest.raises(IntegrityError, match="strains_strain_deaccession_iff_status"),
        transaction.atomic(),
    ):
        Strain.objects.filter(pk=strain.pk).update(deaccession_reason="Half done.")


def test_the_database_asks_a_quarantine_pest_for_its_final_use(
    curator: User, manager: User, pest: Strain, make_strain: MakeStrain
) -> None:
    now = timezone.now()
    raw_proposal(pest, curator, proposed_at=now, confirmed_by=None)
    StrainDeaccessionProposal.objects.filter(strain=pest).update(
        confirmed_by=manager, confirmed_at=now
    )
    with guarded("records its final use"), transaction.atomic():
        raw_leave(pest, manager, deaccessioned_at=now)
    with guarded("records its final use"), transaction.atomic():
        raw_leave(make_strain(), curator, final_use=FinalUse.STORAGE)


def test_a_strain_enters_the_collection_before_it_leaves_it(
    curator: User, make_strain: MakeStrain
) -> None:
    template = make_strain()
    values = {
        f.attname: getattr(template, f.attname)
        for f in Strain._meta.concrete_fields
        if f.attname not in ("id", "public_id", "accession_number", "accession_seq")
    }
    values |= {
        "accession_number": "MYC 999",
        "status": StrainStatus.DEACCESSIONED,
        "deaccessioned_at": timezone.now(),
        "deaccessioned_by_id": curator.pk,
        "deaccession_cause": DeaccessionCause.DUPLICATE,
        "deaccession_reason": "Twice.",
    }
    with guarded("enters the collection before it leaves"), transaction.atomic():
        Strain.objects.create(**values)


def test_a_proposal_is_settled_once_and_never_deleted(
    curator: User, manager: User, gmo: Strain
) -> None:
    proposal = raw_proposal(gmo, curator)
    with guarded("changes once"), transaction.atomic():
        StrainDeaccessionProposal.objects.filter(pk=proposal.pk).update(reason="Other.")
    StrainDeaccessionProposal.objects.filter(pk=proposal.pk).update(
        withdrawn_by=manager, withdrawn_at=timezone.now(), withdraw_reason="It grew."
    )
    with guarded("changes once"), transaction.atomic():
        StrainDeaccessionProposal.objects.filter(pk=proposal.pk).update(withdraw_reason="Other.")
    with guarded("never deleted"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM strains_straindeaccessionproposal WHERE id = %s", [proposal.pk])


def test_a_proposal_is_made_open_for_a_strain_of_its_lab_in_the_collection(
    curator: User, manager: User, other_lab: Lab, gmo: Strain, make_strain: MakeStrain
) -> None:
    with guarded("a proposal is made open"), transaction.atomic():
        raw_proposal(gmo, curator, confirmed_by=manager, confirmed_at=timezone.now())
    with guarded("a proposal is made open"), transaction.atomic():
        StrainDeaccessionProposal.objects.create(
            lab=other_lab,
            strain=gmo,
            cause=DeaccessionCause.LOST,
            reason="x",
            proposed_by=curator,
            proposed_at=timezone.now(),
        )
    gone = make_strain(name_as_received="gone")
    leave(curator, gone)
    with guarded("a proposal is made open"), transaction.atomic():
        raw_proposal(gone, curator)


# "Regulated" is written twice: strains.selectors.regulating_restrictions() and the strain
# guard's "ended_at IS NULL" (ADR 0010, proposed). Each case the predicate tells apart, tried on
# the trigger: it asks for a confirmed proposal exactly when the Python predicate says regulated.

KINDS: dict[RestrictionKind, RestrictionInput] = {
    RestrictionKind.CZ_VRAT: VRAT,
    RestrictionKind.CZ_RAT: RestrictionInput(RestrictionKind.CZ_RAT, "Příloha 2, bod 1"),
    RestrictionKind.DUAL_USE: DUAL_USE,
    RestrictionKind.QUARANTINE_PEST: QUARANTINE,
    RestrictionKind.GMO: GMO,
}


@pytest.mark.parametrize(
    "case", ["none", "ended", *(f"active {kind}" for kind in RestrictionKind.values)]
)
def test_the_trigger_and_the_python_predicate_agree_on_regulated(
    case: str, lab: Lab, curator: User, manager: User, make_strain: MakeStrain
) -> None:
    assert set(KINDS) == set(RestrictionKind)  # a new kind needs a case here
    make_permit(lab, AuthorisationKind.CZ_VRAT)
    make_permit(lab, AuthorisationKind.QUARANTINE_PEST)
    if case == "none":
        strain = make_strain()
    elif case == "ended":
        strain = make_strain(restrictions=[GMO])
        end_restriction(
            StrainRestriction.objects.get(strain=strain), proposer=curator, confirmer=manager
        )
    else:
        strain = make_strain(restrictions=[KINDS[RestrictionKind(case.split()[1])]])
    regulated = selectors.regulating_restrictions().filter(strain=strain).exists()
    pest = (
        selectors.regulating_restrictions()
        .filter(strain=strain, kind=RestrictionKind.QUARANTINE_PEST)
        .exists()
    )
    final_use = FinalUse.DESTRUCTION if pest else ""
    try:
        with transaction.atomic():
            raw_leave(strain, curator, final_use=final_use)
    except (IntegrityError, InternalError) as error:
        assert regulated, f"{case}: refused although not regulated: {error}"
        assert "a second person confirms" in str(error)
    else:
        assert not regulated, f"{case}: one person deaccessioned a regulated strain"


def test_the_runtime_role_works_the_two_steps_and_cannot_skip_them(
    as_curator: AuditContext,
    curator: User,
    manager: User,
    gmo: Strain,
    runtime_role: CursorWrapper,
) -> None:
    refused_sql(
        runtime_role,
        "UPDATE strains_strain SET status = 'deaccessioned', deaccessioned_at = now(),"  # noqa: S608
        f" deaccessioned_by_id = {curator.pk}, deaccession_cause = 'lost',"
        f" deaccession_reason = 'x' WHERE id = {gmo.pk}",
        "a second person confirms a proposal",
    )
    proposal = propose(curator, gmo)
    refused_sql(
        runtime_role,
        "DELETE FROM strains_straindeaccessionproposal",
        "permission denied for table strains_straindeaccessionproposal",
    )
    confirm(manager, gmo, proposal.public_id)
    gmo.refresh_from_db()
    assert gmo.status == StrainStatus.DEACCESSIONED

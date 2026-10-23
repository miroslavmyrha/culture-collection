"""What waits on Home (#69), per role: each kind appears for exactly the people who may handle it,
in their labs, and disappears once handled. Everything is made through the services."""

from datetime import timedelta

import pytest

from cultures.biosafety.models import AuthorisationKind
from cultures.biosafety.policy import permit_today
from cultures.core.testing import logged_in
from cultures.deposits import services as deposits
from cultures.deposits.models import Condition
from cultures.deposits.tests.support import DUAL_USE, MakeDeposit, facts
from cultures.distribution import services as distribution
from cultures.distribution.models import DistributionRequest, PermitKind, Requester
from cultures.distribution.tests.support import (
    Regulated,
    Supply,
    accept_mtas,
    add_permit,
    approve,
    as_actor,
    confirm,
    ship,
    submit,
    withdraw,
)
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import make_user, member_of
from cultures.lineage import services as lineage
from cultures.lineage.models import Batch, CheckKind, CheckResult, VialStatus
from cultures.lineage.tests.support import record, vials_of
from cultures.overview import selectors
from cultures.strains.models import Strain
from cultures.strains.tests.conftest import make_permit
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import OVERVIEW_URL, overview, subjects, waiting

pytestmark = pytest.mark.django_db


def batch_of(strain: Strain) -> Batch:
    return Batch.objects.get(strain=strain)


# Deposits: curators and managers check them.


def test_a_received_deposit_waits_for_curators_and_managers_until_it_is_accepted(
    make_deposit: MakeDeposit, team: dict[Role, User], exempli: Taxon, curator: User
) -> None:
    deposit = make_deposit(
        name_as_received="Testella exempli W1",
        condition=Condition.DAMAGED,
        condition_note="Cracked.",
    )
    for role, user in team.items():
        expected = ["Testella exempli W1"] if role in (Role.CURATOR, Role.MANAGER) else []
        assert subjects(user, "deposit_received") == expected, role
    [item] = waiting(curator)["deposit_received"]
    assert item["target"] == "deposit"
    assert item["target_id"] == str(deposit.public_id)
    assert item["reason"] == "Received, not checked yet. Arrived: container or packaging damaged"
    assert item["since"] == "2026-10-01"

    with as_actor(curator):
        deposit = deposits.deposit_start_check(access=access_for(curator), deposit=deposit)
    assert subjects(curator, "deposit_received") == []
    assert subjects(curator, "deposit_checking") == ["Testella exempli W1"]

    with as_actor(curator):
        deposits.deposit_accept(access=access_for(curator), deposit=deposit, facts=facts(exempli))
    assert "deposit_checking" not in waiting(curator)


# Batches: technicians record checks, curators release and hold.


def test_a_batch_without_its_checks_waits_for_the_bench_then_for_a_release(
    supply: Supply, team: dict[Role, User], curator: User, technician: User
) -> None:
    batch = batch_of(supply(release=False))
    for role, user in team.items():
        expected = [] if role == Role.VIEWER else [f"{batch.strain.accession_number} batch 1"]
        assert subjects(user, "batch_checks_missing") == expected, role
    [item] = waiting(technician)["batch_checks_missing"]
    assert item["reason"] == "No passed identity, purity or viability check yet"
    assert item["target"] == "strain"
    assert item["target_id"] == str(batch.strain.public_id)

    with as_actor(technician):
        record(technician, batch, CheckKind.IDENTITY)
    [item] = waiting(technician)["batch_checks_missing"]
    assert item["reason"] == "No passed purity or viability check yet"

    with as_actor(technician):
        record(technician, batch, CheckKind.PURITY)
        record(technician, batch, CheckKind.VIABILITY, result=CheckResult.REDUCED)
    # Reduced counts as passed (lineage.models.PASSING): the batch waits for a curator now.
    assert waiting(technician) == {}
    for role, user in team.items():
        expected = (
            [f"{batch.strain.accession_number} batch 1"]
            if role in (Role.CURATOR, Role.MANAGER)
            else []
        )
        assert subjects(user, "batch_to_release") == expected, role

    with as_actor(curator):
        lineage.batch_release(access=access_for(curator), batch=batch, reason="All passed.")
    assert waiting(curator).get("batch_to_release") is None


def test_a_held_batch_waits_for_curators_with_its_reason(
    supply: Supply, team: dict[Role, User], curator: User
) -> None:
    batch = batch_of(supply())
    with as_actor(curator):
        lineage.batch_hold(
            access=access_for(curator), batch=batch, reason="Mould on the\nplates of purity."
        )
    for role, user in team.items():
        expected = (
            [f"{batch.strain.accession_number} batch 1"]
            if role in (Role.CURATOR, Role.MANAGER)
            else []
        )
        assert subjects(user, "batch_on_hold") == expected, role
    assert waiting(curator)["batch_on_hold"][0]["reason"] == "Mould on the plates of purity."

    with as_actor(curator):
        lineage.batch_release(access=access_for(curator), batch=batch, reason="Plates read again.")
    assert "batch_on_hold" not in waiting(curator)


# Requests: curators decide and ship; a regulated line is a manager's; two people ship it.


def test_a_request_waits_for_a_decision_then_for_its_shipment(
    supply: Supply, lab: Lab, requester: Requester, team: dict[Role, User], curator: User
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    label = f"Request {request.label}, Example Institute of Microbiology"
    for role, user in team.items():
        expected = [label] if role in (Role.CURATOR, Role.MANAGER) else []
        assert subjects(user, "request_to_decide") == expected, role
    [item] = waiting(curator)["request_to_decide"]
    assert (item["needs_manager"], item["reason"]) == (False, "Entered: approve it or reject it")
    assert (item["target"], item["target_id"]) == ("request", str(request.public_id))

    accept_mtas(curator, request)
    approve(curator, request)
    assert "request_to_decide" not in waiting(curator)
    [item] = waiting(curator)["request_to_ship"]
    assert item["reason"] == "Approved: ship the reserved vials"

    ship(curator, DistributionRequest.objects.get(pk=request.pk))
    assert waiting(curator) == {}


def test_a_request_for_a_regulated_strain_is_flagged_for_a_manager(
    *, supply: Supply, lab: Lab, requester: Requester, mockia: Taxon, curator: User, manager: User
) -> None:
    strain = supply(mockia, restrictions=[DUAL_USE])
    plain = submit(curator, lab, requester, [(supply(), 1)])
    flagged = submit(curator, lab, requester, [(strain, 1)])
    for user in (curator, manager):
        items = {i["target_id"]: i for i in waiting(user)["request_to_decide"]}
        assert items[str(flagged.public_id)]["needs_manager"] is True
        assert (
            items[str(flagged.public_id)]["reason"] == "A regulated strain: a manager approves it"
        )
        assert items[str(plain.public_id)]["needs_manager"] is False


def test_a_prepared_shipment_waits_only_for_a_person_who_may_confirm_it(
    regulated: Regulated, team: dict[Role, User], approver: User, curator: User, manager: User
) -> None:
    """Never for the one who approved it (`approver`), nor for the one who prepared it
    (`curator`): the service refuses both (ADR 0009). A technician may not ship at all."""
    request = regulated(prepared_by=curator)
    label = f"Request {request.label}, Example Institute of Microbiology"
    assert subjects(manager, "shipment_to_confirm") == [label]
    for user in (approver, curator, team[Role.TECHNICIAN], team[Role.VIEWER]):
        assert subjects(user, "shipment_to_confirm") == [], user.username
    [item] = waiting(manager)["shipment_to_confirm"]
    assert item["reason"] == "Prepared: a second person confirms the shipment"

    withdraw(curator, request)
    assert subjects(manager, "shipment_to_confirm") == []
    shippable = {i["target_id"]: i["reason"] for i in waiting(curator)["request_to_ship"]}
    assert (
        shippable[str(request.public_id)]
        == "Approved: prepare the shipment, a second person confirms it"
    )


def test_a_confirmed_shipment_waits_for_nobody(
    regulated: Regulated, team: dict[Role, User], approver: User, curator: User, manager: User
) -> None:
    request = regulated(prepared_by=curator)
    confirm(manager, request)
    for user in (*team.values(), approver):
        assert waiting(user) == {}, user.username


def test_the_approver_who_did_not_prepare_still_may_not_confirm(
    regulated: Regulated, approver: User, curator: User, manager: User
) -> None:
    request = regulated(prepared_by=manager)
    assert subjects(approver, "shipment_to_confirm") == []
    assert subjects(manager, "shipment_to_confirm") == []
    assert subjects(curator, "shipment_to_confirm") == [
        f"Request {request.label}, Example Institute of Microbiology"
    ]


# Permits: managers renew them.


@pytest.mark.parametrize(("days", "shown"), [(-1, False), (0, True), (30, True), (31, False)])
def test_a_recipient_permit_waits_for_managers_within_thirty_days_of_its_expiry(
    days: int, shown: bool, requester: Requester, team: dict[Role, User], curator: User
) -> None:
    today = permit_today()
    add_permit(
        curator,
        requester,
        PermitKind.SUJB_RAT_NOTICE,
        valid_from=today - timedelta(days=60),
        expires_on=today + timedelta(days=days),
    )
    for role, user in team.items():
        found = waiting(user).get("recipient_permit_expiring", [])
        assert len(found) == (1 if shown and role == Role.MANAGER else 0), role
    if shown:
        [item] = waiting(team[Role.MANAGER])["recipient_permit_expiring"]
        assert item["due"] == (today + timedelta(days=days)).isoformat()
        assert (
            item["subject"]
            == "DEV/sujb_rat_notice/1 (invented example), Example Institute of Microbiology"
        )
        assert item["target"] == "requesters"


def test_an_ended_recipient_permit_does_not_wait(
    requester: Requester, curator: User, manager: User
) -> None:
    today = permit_today()
    permit = add_permit(
        curator,
        requester,
        PermitKind.SUJB_RAT_NOTICE,
        valid_from=today - timedelta(days=60),
        expires_on=today + timedelta(days=5),
    )
    with as_actor(curator):
        distribution.permit_end(
            access=access_for(curator), permit=permit, ended_on=today, reason="Replaced."
        )
    assert "recipient_permit_expiring" not in waiting(manager)


@pytest.mark.parametrize(("days", "shown"), [(-1, False), (0, True), (30, True), (31, False)])
def test_a_lab_permit_waits_for_managers_within_thirty_days_of_its_expiry(
    days: int, shown: bool, lab: Lab, team: dict[Role, User]
) -> None:
    make_permit(
        lab,
        AuthorisationKind.CZ_VRAT,
        permit_reference="DEV/VRAT/7",
        expires_on=permit_today() + timedelta(days=days),
    )
    for role, user in team.items():
        found = subjects(user, "lab_permit_expiring")
        assert found == (["SÚJB DEV/VRAT/7"] if shown and role == Role.MANAGER else []), role


def test_an_ended_lab_permit_does_not_wait(lab: Lab, manager: User) -> None:
    today = permit_today()
    make_permit(
        lab,
        AuthorisationKind.CZ_VRAT,
        expires_on=today + timedelta(days=3),
        ended_on=today,
        end_reason="Revoked.",
    )
    assert waiting(manager) == {}


# Vials marked to destroy: curators decide on them.


def test_vials_marked_to_destroy_wait_for_curators_one_line_per_batch(
    supply: Supply, team: dict[Role, User], curator: User
) -> None:
    batch = batch_of(supply(vials=4))
    first, second, *_ = vials_of(batch)
    with as_actor(curator):
        for vial in (first, second):
            lineage.vial_transition(
                access=access_for(curator),
                vial=vial,
                status=VialStatus.TO_DESTROY,
                reason="Cracked tube.",
            )
    for role, user in team.items():
        expected = (
            [f"{batch.strain.accession_number} batch 1"]
            if role in (Role.CURATOR, Role.MANAGER)
            else []
        )
        assert subjects(user, "vials_to_destroy") == expected, role
    [item] = waiting(curator)["vials_to_destroy"]
    assert item["reason"] == "2 vials marked to destroy"
    assert (item["target"], item["target_id"]) == ("strain", str(batch.strain.public_id))

    with as_actor(curator):
        for vial in (first, second):
            lineage.vial_transition(
                access=access_for(curator),
                vial=vial,
                status=VialStatus.DESTROYED,
                reason="Autoclaved.",
            )
    assert "vials_to_destroy" not in waiting(curator)


# Scope: memberships decide, never anything else.


def test_items_of_another_lab_never_show(
    make_deposit: MakeDeposit, other_lab: Lab, outsider: User, curator: User
) -> None:
    make_deposit(name_as_received="Testella exempli W2")
    assert waiting(outsider) == {}
    elsewhere = member_of(other_lab, Role.CURATOR, "elsewhere")
    assert waiting(elsewhere) == {}
    assert subjects(curator, "deposit_received") == ["Testella exempli W2"]


def test_a_person_in_two_labs_sees_each_lab_by_its_own_role(
    make_deposit: MakeDeposit, supply: Supply, lab: Lab, other_lab: Lab
) -> None:
    """Curator in one lab, viewer in the other: the other lab's deposit stays out."""
    person = member_of(other_lab, Role.CURATOR, "two-labs")
    Membership.objects.create(user=person, lab=lab, role=Role.VIEWER)
    make_deposit(name_as_received="Testella exempli W3")
    supply(release=False)
    data = overview(person)
    assert data["waiting"] == []
    assert [(entry["code"], entry["role"]) for entry in data["labs"]] == [
        ("BAC", "curator"),
        ("MYC", "viewer"),
    ]


def test_a_person_in_no_lab_sees_nothing() -> None:
    data = overview(make_user("lonely"))
    assert data == {"waiting": [], "labs": []}


def test_an_inactive_person_gets_401_and_their_access_reads_nothing(
    make_deposit: MakeDeposit, curator: User
) -> None:
    make_deposit()
    curator.is_active = False
    curator.save(update_fields=["is_active"])
    client = logged_in(curator)
    assert client.get(OVERVIEW_URL).status_code == 401
    access = access_for(curator)
    assert (selectors.waiting(access=access), selectors.my_labs(access=access)) == ([], [])


def test_each_kind_keeps_twenty_items_and_says_how_many_wait(
    make_deposit: MakeDeposit, curator: User
) -> None:
    for i in range(selectors.WAITING_LIMIT + 1):
        make_deposit(name_as_received=f"Testella exempli N{i:02}")
    [group] = overview(curator)["waiting"]
    assert (group["kind"], group["total"], len(group["items"])) == ("deposit_received", 21, 20)
    # Oldest first, then in the order received: the 21st waits on the next page of the list.
    assert group["items"][0]["subject"] == "Testella exempli N00"
    assert group["items"][-1]["subject"] == "Testella exempli N19"

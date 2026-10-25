"""seed_e2e: the data Playwright signs in with, the same locally and in CI."""

from io import StringIO

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel, RowChange
from cultures.deposits.models import Deposit, MtaTemplate
from cultures.distribution import services as distribution
from cultures.distribution.models import DistributionRequest, Requester
from cultures.labs.access import access_for
from cultures.labs.management.commands.seed_e2e import (
    COLLEAGUE,
    CURATOR,
    INSTITUTE,
    LAB_CODE,
    OTHER_LAB_CODE,
    OTHER_MANAGER,
    OUTSIDER,
    READY_TO_PREPARE,
    TECHNICIAN,
    UNNOTIFIED,
    VIEWER,
)
from cultures.labs.models import Lab, LocationGrant, Membership
from cultures.labs.permissions import Role
from cultures.lineage.models import Batch, BatchStatus, Vial
from cultures.storage.models import BoxType, StorageUnit
from cultures.taxonomy.models import Rank, Taxon, TaxonStatus
from cultures.users.models import User

pytestmark = pytest.mark.django_db
PASSWORD = "e2e correct horse battery"  # noqa: S105 (the documented local e2e password)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E2E_PASSWORD", PASSWORD)
    monkeypatch.delenv("E2E_USERNAME", raising=False)


def seed() -> str:
    out = StringIO()
    with override_settings(DEBUG=True):
        call_command("seed_e2e", stdout=out)
    return out.getvalue()


@pytest.mark.usefixtures("env")
def test_it_creates_the_user_the_lab_and_the_manager_membership() -> None:
    assert seed() == (
        "e2e-user manages E2E lab; e2e-curator, e2e-technician and e2e-viewer are its curator,"
        " technician and viewer;"
        " e2e-colleague is in no lab; 10 taxa; a depositor, MTA STD and one accepted deposit;"
        " 2 box types; E2E freezer > Rack 1 > Box 1; a regulated strain with two vials in"
        " Box R, revealed by e2e-user; a released batch of the seeded strain; two strains that"
        " may go out, two requesters and five requests, two approved, one of them regulated and"
        " approved by e2e-manager, who is in no lab; e2e-outsider views E2E other lab, which"
        " e2e-other-manager manages\n"
    )
    user = User.objects.get(username="e2e-user")
    lab = Lab.objects.get(code=LAB_CODE)
    assert user.check_password(PASSWORD)
    assert Membership.objects.get(user=user).lab == lab
    assert Membership.objects.get(user=user).role == Role.MANAGER
    colleague = User.objects.get(username=COLLEAGUE)
    assert (colleague.is_active, colleague.has_usable_password()) == (True, False)
    assert not Membership.objects.filter(user=colleague).exists()
    for name, role in (
        (CURATOR, Role.CURATOR),
        (TECHNICIAN, Role.TECHNICIAN),
        (VIEWER, Role.VIEWER),
    ):
        member = User.objects.get(username=name)
        assert member.check_password(PASSWORD)
        assert Membership.objects.get(user=member, lab=lab).role == role
    # The second manager approved the regulated request and left: it signs in only to approve
    # what a test enters, and the e2e user stays the lab's only manager.
    approver = User.objects.get(username="e2e-manager")
    assert approver.is_active
    assert approver.check_password(PASSWORD)
    assert not Membership.objects.filter(user=approver).exists()
    # A viewer of another lab only, for the search test (#76), and that lab's manager, who
    # never signs in.
    other = Lab.objects.get(code=OTHER_LAB_CODE)
    outsider = User.objects.get(username=OUTSIDER)
    assert outsider.check_password(PASSWORD)
    assert [(m.lab, m.role) for m in Membership.objects.filter(user=outsider)] == [
        (other, Role.VIEWER)
    ]
    other_manager = User.objects.get(username=OTHER_MANAGER)
    assert not other_manager.has_usable_password()
    assert [(m.lab, m.role) for m in Membership.objects.filter(user=other_manager)] == [
        (other, Role.MANAGER)
    ]
    synonyms = dict(Taxon.objects.filter(status="synonym").values_list("name", "accepted__name"))
    assert synonyms == {"Vibrio subtilis": "Bacillus subtilis", "Bacillus coli": "Escherichia coli"}
    assert Taxon.objects.get(name="Bacillus subtilis").parent == Taxon.objects.get(name="Bacillus")
    deposit = Deposit.objects.get(lab=lab, name_as_received="B. subtilis e2e seed")
    assert (deposit.status, deposit.depositor.contact.email) == (
        "accepted",
        "e2e.depositor@example.org",
    )
    assert deposit.strain is not None
    assert (deposit.strain.accession_number, deposit.strain.risk_group) == ("E2E 1", 1)
    assert MtaTemplate.objects.get(lab=lab).code == "STD"
    assert sorted(BoxType.objects.values_list("name", "rows", "cols")) == [
        ("100-place cryobox (10 x 10)", 10, 10),
        ("81-place cryobox (9 x 9)", 9, 9),
    ]
    tree = StorageUnit.objects.filter(lab=lab).order_by("path")
    assert [(u.kind, u.name, u.parent.name if u.parent else None) for u in tree] == [
        ("freezer", "E2E freezer", None),
        ("rack", "Rack 1", "E2E freezer"),
        ("box", "Box 1", "Rack 1"),
        ("box", "Box R", "Rack 1"),
    ]
    regulated = Deposit.objects.get(lab=lab, name_as_received="Testella exempli e2e regulated")
    assert regulated.strain is not None
    assert list(regulated.strain.restrictions.values_list("kind", "reference")) == [
        ("cz_rat", "Příloha 2 (invented example)")
    ]
    vials = Vial.objects.filter(batch__strain=regulated.strain).order_by("seq")
    assert [(p.box.name, p.row, p.col) for v in vials for p in v.placements.all()] == [
        ("Box R", 1, 1),
        ("Box R", 1, 2),
    ]
    grant = LocationGrant.objects.get(lab=lab, revoked_at__isnull=True)
    assert grant.user == user
    (released,) = Batch.objects.filter(strain=deposit.strain, status=BatchStatus.RELEASED)
    assert (released.purpose, released.vial_count_created) == ("distribution", 2)
    assert sorted(
        released.checks.values_list("kind", "result", "performed_by__username", "vial__seq")
    ) == [
        ("identity", "pass", TECHNICIAN, 1),
        ("purity", "pass", TECHNICIAN, 1),
        ("viability", "pass", TECHNICIAN, 1),
    ]


# Two strains that may go out (#18), each received, accepted and preserved into 21 vials of
# distribution stock, checked on its first vial and released; two requesters, the first with a
# § 17a notice; five requests, all but the third with an accepted MTA, the fourth approved with
# its vial reserved (#88), the fifth, of the dual-use strain, approved by e2e-manager (#89).
SUPPLY_STRAIN = [
    "deposit_received",
    "deposit_check_started",
    "strain_created",
    "deposit_accepted",
    "passage_created",
    "batch_created",
    *["vial_created"] * 21,
    "vials_created",
    "vial_status_changed",
    *["batch_check_recorded"] * 3,
    "batch_status_changed",
]
DISTRIBUTION = [
    *SUPPLY_STRAIN,
    *SUPPLY_STRAIN,
    "requester_created",
    "recipient_permit_added",
    "requester_created",
    *["request_submitted", "request_line_added", "mta_acceptance_recorded"] * 2,
    "request_submitted",
    "request_line_added",
    "request_submitted",
    "request_line_added",
    "mta_acceptance_recorded",
    "vial_status_changed",
    "request_line_reserved",
    "request_approved",
    "member_added",  # e2e-manager, for the approval of the regulated request
    "request_submitted",
    "request_line_added",
    "mta_acceptance_recorded",
    "vial_status_changed",
    "request_line_reserved",
    "request_approved",
    "member_removed",  # e2e-manager, once it approved
]


@pytest.mark.usefixtures("env")
def test_its_writes_are_audited_as_the_command() -> None:
    seed()
    events = list(AuditEvent.objects.order_by("pk"))
    assert [e.event_type for e in events] == [
        "user_created",
        "user_created",
        "lab_created",
        "member_added",
        "user_created",
        "member_added",
        "user_created",
        "member_added",
        "user_created",
        "member_added",
        "user_created",  # e2e-manager, in no lab until it approves
        # E2E other lab with its manager and e2e-outsider, its viewer (#76)
        "lab_created",
        "user_created",
        "member_added",
        "user_created",
        "member_added",
        *["taxon_created", "taxon_identifier_added"] * 2,
        "taxon_created",
        *["taxon_created", "taxon_identifier_added"] * 2,
        "taxon_created",
        *["taxon_created"] * 4,  # Testella and Mockia, invented
        "depositor_created",
        "mta_template_published",
        "deposit_received",
        "deposit_check_started",
        "strain_created",
        "deposit_accepted",
        "passage_created",
        "box_type_created",
        "box_type_created",
        *["storage_unit_created"] * 3,
        "deposit_received",
        "deposit_check_started",
        "strain_created",
        "deposit_accepted",
        "passage_created",
        "storage_unit_created",
        "batch_created",
        *["vial_created"] * 2,
        "vials_created",
        *["vial_placed"] * 2,
        "vials_placed",
        "location_grant_added",
        "batch_created",
        *["vial_created"] * 2,
        "vials_created",
        "vial_status_changed",  # the first vial, used for the checks
        *["batch_check_recorded"] * 3,
        "batch_status_changed",
        *DISTRIBUTION,
    ]
    assert {(e.channel, e.actor_kind, e.actor_label, e.actor_id) for e in events} == {
        (Channel.COMMAND, ActorKind.SYSTEM, "command:seed_e2e", None)
    }
    # The user rows the command wrote join its events by request id.
    request_ids = set(RowChange.objects.values_list("request_id", flat=True))
    assert request_ids == {events[0].request_id}


@pytest.mark.usefixtures("env")
def test_one_requester_has_an_invented_seat_and_the_other_none() -> None:
    """The second stands for a requester entered before the seat was asked."""
    seed()
    assert dict(Requester.objects.values_list("institution", "seat")) == {
        INSTITUTE: "E2E street 1, 602 00 Brno (invented example)",
        UNNOTIFIED: "",
    }


@pytest.mark.usefixtures("env")
def test_a_second_run_changes_nothing() -> None:
    seed()
    before = (AuditEvent.objects.count(), RowChange.objects.count())
    seed()
    assert (AuditEvent.objects.count(), RowChange.objects.count()) == before


@pytest.mark.usefixtures("env")
def test_a_taxon_written_in_another_case_is_reused_and_gains_its_missing_parent() -> None:
    """The seeds share one rule for taxa (#121): staff's spelling stays, no second taxon."""
    typed = Taxon.objects.create(
        name="bacillus subtilis", authority="", rank=Rank.SPECIES, status=TaxonStatus.ACCEPTED
    )
    seed()
    found = Taxon.objects.filter(name__iexact="Bacillus subtilis", rank=Rank.SPECIES)
    assert list(found) == [typed]
    typed.refresh_from_db()
    assert (typed.name, typed.authority) == ("bacillus subtilis", "")
    assert typed.parent == Taxon.objects.get(name="Bacillus", rank=Rank.GENUS)


@pytest.mark.usefixtures("env")
def test_it_resets_what_a_failed_e2e_run_left_behind() -> None:
    seed()
    user, lab = User.objects.get(username="e2e-user"), Lab.objects.get(code=LAB_CODE)
    colleague = User.objects.get(username=COLLEAGUE)
    Membership.objects.create(user=colleague, lab=lab, role=Role.CURATOR)
    Membership.objects.create(
        user=User.objects.create(username="helper"), lab=lab, role=Role.MANAGER
    )
    Membership.objects.filter(user=user).update(role=Role.VIEWER)
    user.set_password("changed")
    user.is_active = False
    user.save()
    seed()
    user.refresh_from_db()
    assert (user.is_active, user.check_password(PASSWORD)) == (True, True)
    reset = AuditEvent.objects.filter(subject_id=user.public_id).order_by("pk")
    assert [(e.event_type, e.reason) for e in reset][-2:] == [
        ("user_activated", "reset the e2e data"),
        ("user_password_changed", "reset the e2e data"),
    ]
    assert Membership.objects.get(user=user).role == Role.MANAGER
    assert not Membership.objects.filter(user=colleague).exists()


@pytest.mark.usefixtures("env")
def test_a_regulated_request_ready_to_prepare_is_entered_again_once_it_left_approved() -> None:
    """The e2e test prepares and confirms it each run: the next run finds none approved and
    enters a new one, approved by e2e-manager, never by the e2e user who confirms."""
    seed()
    ready = DistributionRequest.objects.get(end_use=READY_TO_PREPARE)
    assert ready.decided_by is not None
    assert (ready.status, ready.decided_by.username) == ("approved", "e2e-manager")
    assert ready.lines.get().strain.restrictions.filter(ended_at__isnull=True).exists()
    manager = User.objects.get(username="e2e-user")
    with audit_context(channel=Channel.API, actor=manager, request_id="req-test"):
        distribution.request_cancel(access=access_for(manager), request=ready, reason="test")
    seed()
    statuses = DistributionRequest.objects.filter(end_use=READY_TO_PREPARE).order_by("pk")
    assert list(statuses.values_list("status", flat=True)) == ["cancelled", "approved"]


@pytest.mark.usefixtures("env")
def test_the_username_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E2E_USERNAME", "ci-user")
    seed()
    assert Membership.objects.get(user__username="ci-user").role == Role.MANAGER


@pytest.mark.usefixtures("env")
def test_it_refuses_to_run_without_debug() -> None:
    with override_settings(DEBUG=False), pytest.raises(CommandError, match="only with DEBUG on"):
        call_command("seed_e2e", stdout=StringIO())
    assert not User.objects.exists()


def test_it_refuses_to_run_without_a_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("E2E_PASSWORD", raising=False)
    monkeypatch.delenv("E2E_PASSWORD_FILE", raising=False)
    with pytest.raises(ImproperlyConfigured, match="E2E_PASSWORD"):
        seed()
    assert not User.objects.exists()


def test_it_refuses_an_empty_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E2E_PASSWORD", " ")
    with pytest.raises(CommandError, match="E2E_PASSWORD is empty"):
        seed()
    assert not User.objects.exists()


def test_help_builds() -> None:
    out = StringIO()
    with pytest.raises(SystemExit):
        call_command("seed_e2e", "--help", stdout=out)

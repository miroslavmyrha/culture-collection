"""seed_e2e: the data Playwright signs in with, the same locally and in CI."""

from io import StringIO

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from cultures.audit.models import ActorKind, AuditEvent, Channel, RowChange
from cultures.deposits.models import Deposit, MtaTemplate
from cultures.labs.management.commands.seed_e2e import COLLEAGUE, CURATOR, LAB_CODE, VIEWER
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.storage.models import BoxType
from cultures.taxonomy.models import Taxon
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
        "e2e-user manages E2E lab; e2e-curator and e2e-viewer are its curator and viewer;"
        " e2e-colleague is in no lab; 8 taxa; a depositor, MTA STD and one accepted deposit;"
        " 2 box types\n"
    )
    user = User.objects.get(username="e2e-user")
    lab = Lab.objects.get(code=LAB_CODE)
    assert user.check_password(PASSWORD)
    assert Membership.objects.get(user=user).lab == lab
    assert Membership.objects.get(user=user).role == Role.MANAGER
    colleague = User.objects.get(username=COLLEAGUE)
    assert (colleague.is_active, colleague.has_usable_password()) == (True, False)
    assert not Membership.objects.filter(user=colleague).exists()
    for name, role in ((CURATOR, Role.CURATOR), (VIEWER, Role.VIEWER)):
        member = User.objects.get(username=name)
        assert member.check_password(PASSWORD)
        assert Membership.objects.get(user=member, lab=lab).role == role
    synonyms = dict(Taxon.objects.filter(status="synonym").values_list("name", "accepted__name"))
    assert synonyms == {"Vibrio subtilis": "Bacillus subtilis", "Bacillus coli": "Escherichia coli"}
    assert Taxon.objects.get(name="Bacillus subtilis").parent == Taxon.objects.get(name="Bacillus")
    deposit = Deposit.objects.get(lab=lab)
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
        *["taxon_created", "taxon_identifier_added"] * 2,
        "taxon_created",
        *["taxon_created", "taxon_identifier_added"] * 2,
        "taxon_created",
        "taxon_created",
        "taxon_created",
        "depositor_created",
        "mta_template_published",
        "deposit_received",
        "deposit_check_started",
        "strain_created",
        "deposit_accepted",
        "passage_created",
        "box_type_created",
        "box_type_created",
    ]
    assert {(e.channel, e.actor_kind, e.actor_label, e.actor_id) for e in events} == {
        (Channel.COMMAND, ActorKind.SYSTEM, "command:seed_e2e", None)
    }
    # The user rows the command wrote join its events by request id.
    request_ids = set(RowChange.objects.values_list("request_id", flat=True))
    assert request_ids == {events[0].request_id}


@pytest.mark.usefixtures("env")
def test_a_second_run_changes_nothing() -> None:
    seed()
    before = (AuditEvent.objects.count(), RowChange.objects.count())
    seed()
    assert (AuditEvent.objects.count(), RowChange.objects.count()) == before


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

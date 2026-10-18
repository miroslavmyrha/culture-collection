"""createsuperuser and changepassword: Django's commands, writing through the audited services."""

from io import StringIO

import pytest
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError

from cultures.audit.models import ActorKind, AuditEvent, Channel, RowChange
from cultures.users.management.commands import changepassword
from cultures.users.models import User

from .conftest import PASSWORD, trail

pytestmark = pytest.mark.django_db
NEW_PASSWORD = "a brand new command password"  # noqa: S105 (a test password)


@pytest.mark.parametrize("name", ["createsuperuser", "changepassword"])
def test_ours_replace_djangos_commands(name: str) -> None:
    assert get_commands()[name] == "cultures.users"


@pytest.mark.parametrize("name", ["createsuperuser", "changepassword"])
def test_help_builds(name: str) -> None:
    with pytest.raises(SystemExit):
        call_command(name, "--help", stdout=StringIO())


def test_createsuperuser_records_the_user_and_both_grants_as_the_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", PASSWORD)
    call_command(
        "createsuperuser",
        "--noinput",
        "--username=root",
        "--email=root@example.org",
        stdout=StringIO(),
    )

    root = User.objects.get(username="root")
    assert (root.is_staff, root.is_superuser, root.check_password(PASSWORD)) == (True, True, True)
    events = list(AuditEvent.objects.order_by("pk"))
    assert [e.event_type for e in events] == [
        "user_created",
        "user_staff_changed",
        "user_superuser_changed",
    ]
    assert {(e.channel, e.actor_kind, e.actor_label, e.actor_id, e.reason) for e in events[1:]} == {
        (
            Channel.COMMAND,
            ActorKind.SYSTEM,
            "command:createsuperuser",
            None,
            "created with manage.py createsuperuser",
        )
    }
    # The row trigger's INSERT and UPDATE rows join the events by request id.
    rows = RowChange.objects.filter(row_pk=str(root.pk))
    assert {r.request_id for r in rows} == {events[0].request_id}
    assert [r.op for r in rows.order_by("pk")] == ["INSERT", "UPDATE", "UPDATE"]


def test_createsuperuser_with_a_taken_username_creates_nothing(
    monkeypatch: pytest.MonkeyPatch, staff: User
) -> None:
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", PASSWORD)
    before = trail()
    with pytest.raises(CommandError, match="already taken"):
        call_command("createsuperuser", "--noinput", "--username=staff", "--email=x@example.org")
    assert trail() == before


@pytest.fixture
def typed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the operator types at the password prompts, in order."""
    answers: list[str] = []
    monkeypatch.setattr(changepassword.Command, "_get_pass", lambda self, prompt="": answers.pop(0))
    return answers


def test_changepassword_saves_through_user_set_password(typed: list[str], staff: User) -> None:
    typed.extend([NEW_PASSWORD, NEW_PASSWORD])
    out = StringIO()
    call_command("changepassword", "staff", stdout=out)

    assert "Password changed successfully for user 'staff'" in out.getvalue()
    staff.refresh_from_db()
    assert staff.check_password(NEW_PASSWORD)
    (event,) = AuditEvent.objects.all()
    assert (event.event_type, event.channel, event.actor_kind, event.actor_label) == (
        "user_password_changed",
        Channel.COMMAND,
        ActorKind.SYSTEM,
        "command:changepassword",
    )
    (row,) = RowChange.objects.filter(request_id=event.request_id)
    assert (row.op, row.new) == ("UPDATE", {"password": "redacted"})


def test_changepassword_retries_a_mismatch_and_a_weak_password(
    typed: list[str], staff: User
) -> None:
    typed.extend(["first try", "second try", "short", "short", NEW_PASSWORD, NEW_PASSWORD])
    err = StringIO()
    call_command("changepassword", "staff", stdout=StringIO(), stderr=err)
    assert "too short" in err.getvalue()
    staff.refresh_from_db()
    assert staff.check_password(NEW_PASSWORD)
    assert AuditEvent.objects.count() == 1


def test_changepassword_gives_up_after_three_tries_and_changes_nothing(
    typed: list[str], staff: User
) -> None:
    typed.extend(["a", "b"] * 3)
    before = trail()
    with pytest.raises(CommandError, match="after 3 attempts"):
        call_command("changepassword", "staff", stdout=StringIO())
    staff.refresh_from_db()
    assert staff.check_password(PASSWORD)
    assert trail() == before


def test_changepassword_for_an_unknown_user_fails(typed: list[str]) -> None:
    with pytest.raises(CommandError, match="does not exist"):
        call_command("changepassword", "nobody", stdout=StringIO())

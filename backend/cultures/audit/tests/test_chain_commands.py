"""manage.py audit_chain_verify: the chains, their anchors, the exit code (ADR 0009, #175).

ADR 0009 asks for a command that verifies the chain. It is read-only, so it runs
as the migration role, which can read everything, or as the runtime role: one
test runs it on a connection acting as the runtime role. It exits 1 on a break,
so the schedule alerts on the exit code.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.backends.utils import CursorWrapper

from cultures.audit import chain
from cultures.audit.context import AuditContext, audited_atomic
from cultures.audit.events import record_event
from cultures.audit.models import AuditEvent
from cultures.audit.registry import EVENT_TYPES
from cultures.audit.timestamping import FAKE_NOTE
from cultures.users.models import User
from cultures.users.services import user_deactivate

from .test_chain import ITEM, SUMMARY, change, tampered

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def chain_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test-only event types of test_chain.py."""
    for kind in (ITEM, SUMMARY):
        monkeypatch.setitem(EVENT_TYPES, kind.code, kind)


@pytest.fixture
def written(member: User, audited: AuditContext) -> list[AuditEvent]:
    user_deactivate(user=member)
    with audited_atomic():
        record_event(ITEM, change())
        record_event(ITEM, change())
    return list(AuditEvent.objects.order_by("id"))


def verify(*args: str) -> tuple[int, str]:
    out = StringIO()
    try:
        call_command("audit_chain_verify", *args, stdout=out)
    except CommandError as error:
        return error.returncode or 1, out.getvalue() + str(error)
    return 0, out.getvalue()


@pytest.mark.rule("R-AUDIT-05")
def test_intact_chains_are_reported_and_the_command_exits_zero(written: list[AuditEvent]) -> None:
    code, output = verify()
    assert code == 0, output
    assert "event: " in output
    assert "row_change: " in output
    assert "intact" in output
    assert "never anchored" in output  # nothing outside vouches for it yet


@pytest.mark.rule("R-AUDIT-05")
def test_a_break_exits_one_and_names_the_row(written: list[AuditEvent]) -> None:
    target = written[1]
    tampered(
        "audit_auditevent",
        "UPDATE audit_auditevent SET reason = 'rewritten' WHERE id = %s",
        [target.pk],
    )
    code, output = verify()
    assert code == 1
    assert f"first break content_mismatch at row {target.pk}" in output
    assert "a column was changed" in output
    assert "broken: event" in output


@pytest.mark.rule("R-AUDIT-05")
def test_a_removed_row_exits_one_and_names_the_next_row(written: list[AuditEvent]) -> None:
    target, after = written[1], written[2]
    tampered("audit_auditevent", "DELETE FROM audit_auditevent WHERE id = %s", [target.pk])
    code, output = verify("--chain", "event")
    assert code == 1
    assert f"first break prev_mismatch at row {after.pk}" in output
    assert "row_change" not in output  # one chain only


@pytest.mark.rule("R-AUDIT-05")
def test_a_break_inside_stamped_history_exits_one(written: list[AuditEvent]) -> None:
    """A break under an anchor is not only a break: it is a break in stamped history."""
    assert verify()[0] == 0
    call_command("audit_chain_anchor", stdout=StringIO())
    tampered(
        "audit_auditevent",
        "UPDATE audit_auditevent SET reason = 'rewritten' WHERE id = %s",
        [written[-1].pk],
    )
    code, output = verify("--chain", "event")
    assert code == 1
    assert "anchor_covers_break" in output
    assert "stamped at" in output


@pytest.mark.rule("R-AUDIT-05")
def test_an_anchor_catches_a_rewrite_the_chain_itself_cannot(written: list[AuditEvent]) -> None:
    """The head is rewritten and its hash recomputed, so the chain walks clean.

    This is the attacker ADR 0009 names: "Someone who can edit rows can recompute the
    chain, but the stamped heads then no longer match." Nothing but the anchor sees it.
    """
    assert verify()[0] == 0
    call_command("audit_chain_anchor", stdout=StringIO())
    head = written[-1]
    recomputed = chain.hash_sql(chain.EVENT, chain.VERSION, "audit_auditevent", "chain_prev")
    tampered(
        "audit_auditevent",
        "UPDATE audit_auditevent SET reason = 'rewritten' WHERE id = %s",
        [head.pk],
    )
    tampered(
        "audit_auditevent",
        f"UPDATE audit_auditevent SET chain_hash = {recomputed} WHERE id = %s",  # noqa: S608
        [head.pk],
    )
    assert chain.walk(chain.EVENT).first_break is None  # the chain alone sees nothing
    code, output = verify("--chain", "event")
    assert code == 1
    assert "anchor_hash_mismatch" in output
    assert "the anchor stamped" in output


@pytest.mark.rule("R-AUDIT-05")
def test_the_command_says_what_it_did_not_check_about_a_token(written: list[AuditEvent]) -> None:
    call_command("audit_chain_anchor", stdout=StringIO())
    code, output = verify()
    assert code == 0, output
    assert FAKE_NOTE in output
    assert "last anchored" in output


@pytest.mark.rule("R-AUDIT-05")
def test_the_command_runs_as_the_runtime_role(
    written: list[AuditEvent], runtime_role: CursorWrapper
) -> None:
    """Read-only: SELECT on the two chains and the anchors is all it needs."""
    code, output = verify()
    assert code == 0, output
    assert "intact" in output


@pytest.mark.rule("R-AUDIT-05")
def test_an_empty_database_has_nothing_to_report() -> None:
    code, output = verify()
    assert code == 0, output
    assert "0 rows" in output

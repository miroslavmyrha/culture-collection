"""The anchors of ADR 0009: the daily job, a failing authority, a missed day, and who writes.

The chain alone is evidence only against someone who cannot recompute it
(ADR 0009, Alternatives considered). The anchors are the outside evidence, so
what matters here is that an anchor names a head that really existed with the
hash it really had, that nobody but the job can write one, and that a day without
the authority costs a gap in the anchors and nothing else.
"""

import uuid
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.db.backends.utils import CursorWrapper
from model_bakery import baker
from pytest_django.fixtures import Settings

from cultures.audit import anchors, chain
from cultures.audit.context import AuditContext, audited_atomic
from cultures.audit.events import record_event
from cultures.audit.models import AppendOnly, ChainAnchor
from cultures.audit.registry import EVENT_TYPES
from cultures.audit.timestamping import FAKE, FAKE_PREFIX, NoAuthority, Unavailable
from cultures.users.models import User
from cultures.users.services import user_deactivate

from .conftest import refused
from .test_chain import ITEM, SUMMARY, change

pytestmark = pytest.mark.django_db


class FailingAuthority:
    """A provider that cannot be reached. AUDIT_TIMESTAMP_AUTHORITY points here in one test."""

    def __init__(self, **options: Any) -> None:
        self.options = options

    def stamp(self, digest: bytes) -> Any:
        raise Unavailable("the provider answered 503")


FAILING = {"BACKEND": "cultures.audit.tests.test_anchors.FailingAuthority", "OPTIONS": {}}
NONE_AT_ALL = {"BACKEND": "cultures.audit.timestamping.NoAuthority", "OPTIONS": {}}
ANCHOR_COLUMNS = ("public_id", "chain", "head_id", "head_hash", "authority", "token", "token_time")


@pytest.fixture(autouse=True)
def chain_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test-only event types of test_chain.py, so record_event works here too."""
    for kind in (ITEM, SUMMARY):
        monkeypatch.setitem(EVENT_TYPES, kind.code, kind)


@pytest.fixture
def member() -> User:
    """The user the service write acts on, with a name: no anchor may hold any of its values."""
    user: User = baker.make(
        User,
        username="member",
        email="member@example.org",
        first_name="Ada",
        last_name="Lovelace",
    )
    return user


@pytest.fixture
def written(member: User, audited: AuditContext) -> None:
    """Rows in both chains: a service write and two more events."""
    user_deactivate(user=member)
    with audited_atomic():
        record_event(ITEM, change())
        record_event(ITEM, change())


def run(*args: str) -> tuple[int, str]:
    out = StringIO()
    try:
        call_command("audit_chain_anchor", *args, stdout=out)
    except CommandError as error:
        return error.returncode or 1, out.getvalue() + str(error)
    return 0, out.getvalue()


def anchor_rows() -> list[ChainAnchor]:
    return list(ChainAnchor.objects.order_by("id"))


@pytest.mark.rule("R-AUDIT-04")
def test_the_job_stamps_each_chains_head(written: None) -> None:
    code, output = run()
    assert code == 0, output
    found = anchor_rows()
    assert {one.chain for one in found} == set(chain.CHAINS)
    for one in found:
        table = chain.CHAINS[one.chain]
        head = chain.head(table)
        assert head is not None
        assert (one.head_id, bytes(one.head_hash)) == head
        assert one.authority == FAKE
        assert bytes(one.token).startswith(FAKE_PREFIX)
        assert one.token_time is not None
        assert chain.verify(table).intact


@pytest.mark.rule("R-AUDIT-04")
def test_the_job_twice_writes_no_second_anchor(written: None) -> None:
    assert run()[0] == 0
    before = [one.pk for one in anchor_rows()]
    code, output = run()
    assert code == 0, output
    assert [one.pk for one in anchor_rows()] == before
    assert "covered" in output


@pytest.mark.rule("R-AUDIT-04")
def test_a_failing_authority_leaves_the_head_unanchored_and_alerts(
    written: None, member: User, audited: AuditContext, settings: Settings
) -> None:
    """The job exits non-zero and writes nothing; the chain and every write go on."""
    settings.AUDIT_TIMESTAMP_AUTHORITY = FAILING
    code, output = run()
    assert code == 1
    assert "unanchored" in output
    assert "503" in output
    assert anchor_rows() == []
    with audited_atomic():
        record_event(ITEM, change())  # a write after the failure is not blocked
    assert chain.verify(chain.EVENT).intact


@pytest.mark.rule("R-AUDIT-04")
def test_the_default_authority_stamps_nothing(written: None, settings: Settings) -> None:
    settings.AUDIT_TIMESTAMP_AUTHORITY = NONE_AT_ALL
    with pytest.raises(Unavailable, match="no timestamp authority is configured"):
        NoAuthority().stamp(b"x" * 32)
    code, output = run("--chain", "event")
    assert code == 1
    assert anchor_rows() == []
    assert "AUDIT_TIMESTAMP_BACKEND" in output


@pytest.mark.rule("R-AUDIT-04")
def test_a_missed_run_leaves_a_gap_in_the_anchors_only(
    written: None, audited: AuditContext
) -> None:
    """The job runs, rows are written while nobody anchors, the job runs again.

    The rows written in between are covered by the later anchor, so the chain has no
    gap and only the anchors do (ADR 0009, Consequences). The days are the runs, not
    calendar dates: anchored_at comes from the database clock, which time-machine
    cannot move.
    """
    assert run("--chain", "event")[0] == 0
    (first,) = chain.anchors(chain.EVENT)
    with audited_atomic():
        record_event(ITEM, change())
        record_event(ITEM, change())
    assert run("--chain", "event")[0] == 0
    found = chain.anchors(chain.EVENT)
    assert [one.head_id for one in found] == [first.head_id, first.head_id + 2]
    assert chain.verify(chain.EVENT).intact


@pytest.mark.rule("R-AUDIT-05")
def test_an_anchor_over_a_head_that_never_held_that_hash_is_refused(written: None) -> None:
    head = chain.head(chain.EVENT)
    assert head is not None
    with (
        pytest.raises(DatabaseError, match="an anchor names the real head"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            anchors.RECORD, ["event", head[0], b"\x00" * 32, "x", b"t", None, uuid.uuid4()]
        )
    assert anchor_rows() == []


@pytest.mark.rule("R-AUDIT-05")
def test_an_anchor_over_a_row_that_does_not_exist_is_refused(written: None) -> None:
    with (
        pytest.raises(DatabaseError, match="an anchor names the real head"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            anchors.RECORD, ["event", 10_000_000, b"\x00" * 32, "x", b"t", None, uuid.uuid4()]
        )


@pytest.mark.rule("R-AUDIT-05")
def test_the_runtime_role_cannot_write_the_anchor_table(
    written: None, runtime_role: CursorWrapper
) -> None:
    """It may read anchors and call the function that checks them, nothing else."""
    runtime_role.execute("SELECT count(*) FROM audit_chainanchor")
    refused(
        runtime_role,
        "INSERT INTO audit_chainanchor (public_id, chain, head_id, head_hash, anchored_at,"
        " authority, token) VALUES (gen_random_uuid(), 'event', 1, sha256('x'), now(), 'x', 'x')",
        "permission denied for table audit_chainanchor",
    )
    refused(
        runtime_role,
        "UPDATE audit_chainanchor SET authority = 'forged'",
        "permission denied for table audit_chainanchor",
    )
    refused(
        runtime_role,
        "DELETE FROM audit_chainanchor",
        "permission denied for table audit_chainanchor",
    )
    refused(
        runtime_role,
        "TRUNCATE audit_chainanchor",
        "permission denied for table audit_chainanchor",
    )


@pytest.mark.rule("R-AUDIT-05")
def test_the_runtime_role_may_record_an_anchor_through_the_function(
    written: None, runtime_role: CursorWrapper
) -> None:
    head = chain.head(chain.EVENT)
    assert head is not None
    runtime_role.execute(
        anchors.RECORD, ["event", head[0], head[1], FAKE, b"token", None, uuid.uuid4()]
    )
    assert runtime_role.fetchone() is not None
    runtime_role.execute("SELECT chain, head_id FROM audit_chainanchor")
    assert runtime_role.fetchone() == ("event", head[0])


@pytest.mark.rule("R-AUDIT-05")
def test_an_anchor_is_never_changed_or_deleted(written: None) -> None:
    assert run()[0] == 0
    found = anchor_rows()[0]
    found.authority = "rewritten"
    with pytest.raises(AppendOnly):
        found.save()
    with pytest.raises(AppendOnly):
        found.delete()
    with pytest.raises(AppendOnly):
        ChainAnchor.objects.update(authority="rewritten")
    with pytest.raises(AppendOnly):
        ChainAnchor.objects.all().delete()
    with (
        pytest.raises(DatabaseError, match="audit_chainanchor is append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("UPDATE audit_chainanchor SET authority = 'forged'")


@pytest.mark.rule("R-AUDIT-04")
def test_the_anchors_verify_in_a_session_with_other_time_settings(written: None) -> None:
    """Nothing of the anchor path renders a timestamp into hashed or compared content.

    audit_chain_anchor_record compares only bytea against bytea (the head's hash);
    anchored_at and token_time are stored as timestamps and never rendered, and the token
    is kept byte for byte. So a verifier in another zone must find the anchors matching,
    as it must find the chain intact (test_chain.py, the session's time settings).
    """
    assert run()[0] == 0
    assert anchor_rows()
    # Only the zone here, not DateStyle: reading an anchor reads its anchored_at, and psycopg
    # refuses to parse a timestamptz under a non-ISO DateStyle at all ("can't parse timestamptz
    # with DateStyle 'German, DMY'"), so no Django code runs in such a session. The chain's own
    # payload is checked under both settings in test_chain.py, which reads back only bytea.
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL TIME ZONE 'America/New_York'")
        cursor.execute("SELECT current_setting('TimeZone')")
        assert cursor.fetchone() == ("America/New_York",)
    for table in chain.CHAINS.values():
        report = chain.verify(table)
        assert report.anchors, table.name
        assert report.findings == [], (table.name, report.findings)
        assert report.intact, (table.name, report.walked.first_break)
    # Anchoring again in this session is still a no-op: a head is matched by its hash.
    before = [one.pk for one in anchor_rows()]
    code, output = run()
    assert code == 0, output
    assert "covered" in output
    assert [one.pk for one in anchor_rows()] == before


@pytest.mark.rule("R-AUDIT-04")
def test_an_anchor_holds_no_personal_value(written: None, member: User) -> None:
    """An anchor is a hash, a row id, a time, the authority's name and its token.

    Nothing about a person can reach it: the job passes no user value, and the
    table is in NOT_ROW_AUDITED with that reason.
    """
    assert run()[0] == 0
    with connection.cursor() as cursor:
        read = ", ".join(f"{name}::text" for name in ANCHOR_COLUMNS)  # a constant of this file
        cursor.execute(f"SELECT {read} FROM audit_chainanchor")  # noqa: S608
        stored = [value or "" for row in cursor.fetchall() for value in row]
    for personal in (member.username, member.email, member.first_name, member.last_name):
        assert personal
        assert not any(personal in value for value in stored), personal


@pytest.mark.rule("R-AUDIT-04")
def test_help_builds() -> None:
    for name in ("audit_chain_anchor", "audit_chain_verify"):
        with pytest.raises(SystemExit):
            call_command(name, "--help", stdout=StringIO())

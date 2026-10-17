"""app.actor_id and app.request_id are claims any session can set (migration 0008).

The trigger keeps an actor id only when it is a bigint and cuts the request id
to 64 characters. Whatever the value, the write goes through and is recorded.
"""

from typing import Any

import pytest
from django.db import connection, transaction

from cultures.audit.context import audit_context
from cultures.audit.models import Channel, RowChange
from cultures.users.models import User

pytestmark = pytest.mark.django_db

BIGINT_MAX = 9223372036854775807


def write_with(actor_id: str, request_id: str = "", *, truncate: bool = False) -> RowChange:
    """A raw write in a session that set both settings itself, as psql could."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.actor_id', %s, true), set_config('app.request_id', %s, true)",
            [actor_id, request_id],
        )
        if truncate:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("TRUNCATE labs_membership")
        else:
            cursor.execute(
                "UPDATE users_user SET first_name = first_name || 'x' WHERE id = %s", [USER_ID[0]]
            )
    return RowChange.objects.order_by("pk").last()  # type: ignore[return-value]


USER_ID: list[int] = []


@pytest.fixture(autouse=True)
def user(member: User) -> User:
    USER_ID[:] = [member.pk]
    return member


@pytest.mark.parametrize("truncate", [False, True], ids=["row", "truncate"])
@pytest.mark.parametrize(
    ("claim", "actor_id", "invalid"),
    [
        ("42", 42, False),
        ("0000042", 42, False),
        (str(BIGINT_MAX), BIGINT_MAX, False),
        ("", None, False),  # no claim at all: null, not invalid
        (str(BIGINT_MAX + 1), None, True),  # 19 digits, above the bigint range
        ("1" * 20, None, True),
        ("not-a-number", None, True),
        ("-1", None, True),
        (" 42", None, True),
        ("42 ", None, True),
        ("4e2", None, True),
        ("٤٢", None, True),  # Arabic-Indic digits: \d could match them, the cast fails
        ("42; DROP TABLE users_user", None, True),
    ],
)
def test_the_actor_claim_is_kept_only_when_it_is_a_bigint(
    claim: str, actor_id: int | None, invalid: bool, truncate: bool
) -> None:
    change = write_with(claim, truncate=truncate)
    assert change.op == ("TRUNCATE" if truncate else "UPDATE")
    assert (change.actor_id, change.actor_claim_invalid) == (actor_id, invalid)


@pytest.mark.parametrize("truncate", [False, True], ids=["row", "truncate"])
@pytest.mark.parametrize(
    ("claim", "stored"),
    [
        ("req-1", "req-1"),
        ("r" * 64, "r" * 64),
        ("r" * 65, "r" * 64),
        ("x" * 5000, "x" * 64),
        ("", None),
    ],
)
def test_the_request_id_is_cut_to_64_characters(
    claim: str, stored: str | None, truncate: bool
) -> None:
    change = write_with("", claim, truncate=truncate)
    assert change.request_id == stored


def test_a_malformed_claim_does_not_block_later_writes_in_the_session() -> None:
    """The review's case: one bad set_config made every regulated write of the session fail."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.actor_id', 'not-a-number', false)")  # session-wide
        cursor.execute("SELECT set_config('app.request_id', %s, false)", ["y" * 100])
        try:
            for _ in range(2):
                cursor.execute(
                    "UPDATE users_user SET first_name = first_name || 'x' WHERE id = %s",
                    [USER_ID[0]],
                )
        finally:
            cursor.execute("RESET app.actor_id")
            cursor.execute("RESET app.request_id")
    changes = list(RowChange.objects.filter(op="UPDATE").order_by("pk"))
    assert [(c.actor_id, c.actor_claim_invalid, c.request_id) for c in changes] == [
        (None, True, "y" * 64)
    ] * 2


@pytest.mark.parametrize("request_id", ["", "r" * 65, "has space", "line\nbreak", "ünïcode"])
def test_audit_context_refuses_a_request_id_the_tables_cannot_hold(request_id: str) -> None:
    with (
        pytest.raises(ValueError, match="request_id"),
        audit_context(channel=Channel.COMMAND, request_id=request_id),
    ):
        pass  # pragma: no cover


@pytest.mark.parametrize("request_id", ["cmd-1", "r" * 64, "0f" * 16])
def test_audit_context_accepts_a_request_id_like_the_header(request_id: str) -> None:
    kwargs: dict[str, Any] = {"channel": Channel.COMMAND, "request_id": request_id}
    with audit_context(**kwargs) as context:
        assert context.request_id == request_id

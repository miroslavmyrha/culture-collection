"""Who is writing and from where, for both audit layers.

The context lives in a ContextVar:
- inside a request, AuditRequestMiddleware makes the request the source: the
  actor is the authenticated user (read when the event is written, so DRF's
  authentication has run), the request id is the scaffold's X-Request-ID;
- commands, tasks and imports enter audit_context(...) themselves;
- anywhere else current_context() raises MissingAuditContext (fail closed), so a
  write path that forgot its context breaks in tests instead of writing an
  event with no actor.

audited_atomic() opens the transaction for an audited write and hands the
actor and request id to the database row trigger with set_config, so the
trigger's RowChange rows can be joined to the service events.
"""

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from django.db import connections, transaction
from django.http import HttpRequest, HttpResponse

from cultures.core.request_id import NO_REQUEST, current_request_id
from cultures.users.models import User

from .models import ActorKind, Channel


def _request_or_new_id() -> str:
    """Inside a request keep its id, so a nested context still joins the request's rows."""
    request_id = current_request_id()
    return request_id if request_id != NO_REQUEST else uuid.uuid4().hex


@dataclass(frozen=True)
class AuditContext:
    channel: Channel
    actor: User | None = None
    actor_kind: ActorKind = ActorKind.USER
    actor_label: str = ""  # for actors that are not users ("command:import_strains")
    reason: str = ""
    request_id: str = field(default_factory=_request_or_new_id)


class MissingAuditContext(RuntimeError):
    """An audited write ran outside a request and outside audit_context()."""


_context: ContextVar[AuditContext | None] = ContextVar("audit_context", default=None)
_request: ContextVar[HttpRequest | None] = ContextVar("audit_request", default=None)


@contextmanager
def audit_context(
    *,
    channel: Channel,
    actor: User | None = None,
    actor_kind: ActorKind = ActorKind.USER,
    actor_label: str = "",
    reason: str = "",
    request_id: str | None = None,
) -> Iterator[AuditContext]:
    """Enter for commands, tasks and imports. A nested context restores the outer one."""
    context = AuditContext(
        channel=channel,
        actor=actor,
        actor_kind=actor_kind,
        actor_label=actor_label,
        reason=reason,
        **({"request_id": request_id} if request_id is not None else {}),
    )
    token = _context.set(context)
    try:
        yield context
    finally:
        _context.reset(token)


def current_context() -> AuditContext:
    context = _context.get()
    if context is not None:
        return context
    request = _request.get()
    if request is not None:
        user = request.user
        return AuditContext(
            channel=Channel.API,
            actor=user if isinstance(user, User) and user.is_authenticated else None,
            request_id=current_request_id(),
        )
    raise MissingAuditContext("audited write outside a request: wrap it in audit_context()")


class AuditRequestMiddleware:
    """Makes the request the audit context. After AuthenticationMiddleware in MIDDLEWARE.

    Reset in finally with the token: unlike the request id, nothing reads the
    audit context after the response, and a reused worker thread must not
    carry it into the next request.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        token = _request.set(request)
        try:
            return self.get_response(request)
        finally:
            _request.reset(token)


# One statement: both settings are transaction-local (the third argument), so
# they end with the transaction and never leak into the next one on a pooled
# connection. The trigger reads them with current_setting(name, true).
_SET = "SELECT set_config('app.actor_id', %s, true), set_config('app.request_id', %s, true)"
_GET = "SELECT current_setting('app.actor_id', true), current_setting('app.request_id', true)"


@contextmanager
def audited_atomic(using: str = "default") -> Iterator[AuditContext]:
    """transaction.atomic() for audited writes, with the context handed to the row trigger.

    Raises MissingAuditContext before opening the transaction when there is no
    context. set_config runs only after atomic() has opened: in autocommit a
    local setting would last one statement. Nested inside another transaction
    it restores the outer values on exit, because a transaction-local setting
    outlives a released savepoint. A nested block that rolls back needs no
    restore: ROLLBACK TO SAVEPOINT reverts set_config itself.
    """
    context = current_context()
    actor_id = str(context.actor.pk) if context.actor is not None else ""
    connection = connections[using]
    nested = connection.in_atomic_block
    outer: tuple[str, str] | None = None
    with transaction.atomic(using=using):
        with connection.cursor() as cursor:
            if nested:
                cursor.execute(_GET)
                outer = cursor.fetchone()
            cursor.execute(_SET, [actor_id, context.request_id])
        yield context
        # After set_rollback(True) no query may run, and the savepoint rollback restores anyway.
        if outer is not None and not connection.needs_rollback:
            with connection.cursor() as cursor:
                cursor.execute(_SET, [value or "" for value in outer])


@contextmanager
def migration_audit(name: str, *, reason: str) -> Iterator[AuditContext]:
    """audited_atomic() for RunPython data migrations that change regulated tables.

    Without it the row trigger records the migration's changes with no request
    id, like a psql session. Inside it they share a request id with the events
    the migration records: channel "migration", actor kind system, labelled
    "migration:<name>". Data migrations import this function, so what it does
    must stay stable: change it by adding a new one.
    """
    with (
        audit_context(
            channel=Channel.MIGRATION,
            actor_kind=ActorKind.SYSTEM,
            actor_label=f"migration:{name}",
            reason=reason,
        ) as context,
        audited_atomic(),
    ):
        yield context

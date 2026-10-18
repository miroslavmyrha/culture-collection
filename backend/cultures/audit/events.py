"""Writing service events: record_event() for one change, record_batch() for many.

Call both inside the service's audited_atomic(), never after commit: the event
and the change commit or roll back together. Both raise MissingAuditContext
without a context, and RuleViolation when the type needs a reason and none is
given (the database refuses it too).

No personal value enters an event (ADR 0005, update of 2026-10-18): a user
actor is labelled `user:<public_id>`, and a personal field of the subject
(registry.PERSONAL_FIELDS) is stored as "changed" whatever the service passed.
Readers that show a name render it through the actor FK at read time.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from cultures.core.exceptions import RuleViolation
from cultures.users.models import User

from .context import AuditContext, MissingAuditContext, current_context
from .models import ActorKind, AuditEvent
from .registry import EVENT_TYPES, PERSONAL_CHANGED, PERSONAL_FIELDS, EventType

BATCH_SUBJECT = "batch"


@dataclass(frozen=True)
class Change:
    subject_type: str
    subject_id: uuid.UUID
    # {field: [old, new]} from the persisted state; a personal field: "changed"
    changes: dict[str, Any]
    lab_id: int | None = None  # the tenant, for every change to a lab's data


def actor_label(actor: User) -> str:
    """A pseudonym that outlives the name: the public id never changes, erasure keeps it."""
    return f"user:{actor.public_id}"


def _without_personal(change: Change) -> dict[str, Any]:
    personal = PERSONAL_FIELDS.get(change.subject_type, ())
    return {
        field: PERSONAL_CHANGED if field in personal else value
        for field, value in change.changes.items()
    }


def _build(
    event_type: EventType,
    context: AuditContext,
    change: Change,
    *,
    reason: str,
    batch_id: uuid.UUID | None,
) -> AuditEvent:
    actor = context.actor
    kind = ActorKind.USER if actor is not None else context.actor_kind
    if kind == ActorKind.USER and actor is None:
        raise MissingAuditContext("an audited write needs an actor: nobody is signed in")
    return AuditEvent(
        event_type=event_type.code,
        actor=actor,
        actor_label=actor_label(actor) if actor is not None else context.actor_label,
        actor_kind=kind,
        lab_id=change.lab_id,
        channel=context.channel,
        request_id=context.request_id,
        batch_id=batch_id,
        reason=reason,
        subject_type=change.subject_type,
        subject_id=change.subject_id,
        changes=_without_personal(change),
    )


def _checked(event_type: EventType, context: AuditContext, reason: str | None) -> str:
    if EVENT_TYPES.get(event_type.code) is not event_type:
        raise ValueError(f"unregistered audit event type {event_type.code!r}")
    text = context.reason if reason is None else reason
    if event_type.reason_required and not text.strip():
        raise RuleViolation("A reason is required.", code="reason_required", attr="reason")
    return text


def record_event(event_type: EventType, change: Change, *, reason: str | None = None) -> AuditEvent:
    """One event. `reason` overrides the context's reason (an API write passes the user's)."""
    context = current_context()
    text = _checked(event_type, context, reason)
    event = _build(event_type, context, change, reason=text, batch_id=None)
    event.save()
    return event


def record_batch(
    item_type: EventType,
    batch_type: EventType,
    changes: Sequence[Change],
    *,
    reason: str | None = None,
) -> list[AuditEvent]:
    """One event per object plus one batch event, in one bulk_create.

    All of them share batch_id, request_id and occurred_at (the transaction's
    start time from the column default). The batch event's subject is the
    batch itself and its changes hold the count.
    """
    context = current_context()
    text = _checked(item_type, context, reason)
    _checked(batch_type, context, reason)
    batch_id = uuid.uuid4()
    summary = Change(BATCH_SUBJECT, batch_id, {"count": [None, len(changes)]})
    events = [
        *(_build(item_type, context, c, reason=text, batch_id=batch_id) for c in changes),
        _build(batch_type, context, summary, reason=text, batch_id=batch_id),
    ]
    return AuditEvent.objects.bulk_create(events)

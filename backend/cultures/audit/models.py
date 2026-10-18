"""The two audit tables: service events (the meaning) and row changes (the backstop).

Both are append-only on three levels:
- the models refuse changes;
- database triggers (migration 0002) refuse UPDATE and DELETE from every role,
  the owner included, and TRUNCATE from every role except the table owner
  (Django's flush in transactional tests runs as the owner);
- production runs the app as the runtime role of ADR 0005, which owns
  nothing, with only SELECT and INSERT on audit_auditevent and only SELECT on
  audit_rowchange (the row trigger writes it as SECURITY DEFINER). roles.py
  holds those grants and `manage.py db_roles` applies them. In development
  the app connects as the owner, so the grants cannot hold there:
  tests/test_roles.py and tests/test_append_only.py set the roles up inside
  the test transaction.

AuditEvent.lab is the tenant (#9): events about a lab's data carry it, so a
lab's timeline is one indexed query, and reads go through the lab scope like
every other lab-owned row. Events about users have no lab.

AuditEvent.strain_id is the timeline root (ADR 0008, D13): every event about a
strain or anything under it (deposit, passage, batch, vial, check, placement,
request line) carries the strain's public id, so the strain's history is one
indexed query and needs no walk through the tree. No foreign key: the strain
table comes later, and an event must outlive the row it names, like
subject_id. Events about users and labs have no strain.
"""

from typing import Any, NoReturn

from django.conf import settings
from django.contrib.postgres.indexes import BrinIndex
from django.db import models
from django.db.models import Q

from cultures.labs.querysets import LabScopedQuerySet

from .registry import reason_required_codes


class AppendOnly(Exception):
    """Audit rows are never changed or deleted."""


class AppendOnlyQuerySet[T: models.Model](models.QuerySet[T]):
    def update(self, **kwargs: Any) -> NoReturn:
        raise AppendOnly("audit rows are append-only")

    def delete(self) -> NoReturn:
        raise AppendOnly("audit rows are append-only")


# The ignore: django-stubs gives each QuerySet class its own as_manager() return type, so
# two QuerySet bases always "conflict" for mypy. At run time as_manager() builds one manager.
class AuditEventQuerySet(  # type: ignore[override]
    AppendOnlyQuerySet["AuditEvent"], LabScopedQuerySet["AuditEvent"]
):
    """Append-only, and scoped by lab for reads (for_access)."""


class TransactionNow(models.Func):
    """The transaction's start time: every row of one transaction shares it."""

    template = "TRANSACTION_TIMESTAMP()"
    output_field = models.DateTimeField()


class CurrentTransactionId(models.Func):
    """pg_current_xact_id() as bigint (xid8 has no cast to bigint, text has)."""

    template = "pg_current_xact_id()::text::bigint"
    output_field = models.BigIntegerField()


class ActorKind(models.TextChoices):
    USER = "user"
    SYSTEM = "system"
    INSTRUMENT = "instrument"
    API_KEY = "api_key"


class Channel(models.TextChoices):
    WEB = "web"
    API = "api"
    COMMAND = "command"
    TASK = "task"
    IMPORT = "import"
    MIGRATION = "migration"  # a data migration (context.migration_audit)


class Op(models.TextChoices):
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    TRUNCATE = "TRUNCATE"


class AuditEvent(models.Model):
    """One business event, written in the same transaction as the change."""

    occurred_at = models.DateTimeField(db_default=TransactionNow())
    # Joins the event to the RowChange rows of its transaction, also where request_id
    # cannot (a command and a psql fix in one session have different transactions).
    txid = models.BigIntegerField(db_default=CurrentTransactionId())
    event_type = models.CharField(max_length=60)  # a code from registry.EVENT_TYPES
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )
    # user:<public_id> for a user (never a name: it must outlive an erasure), else the
    # system actor's label ("command:seed_e2e"). Show a user's name through `actor`.
    actor_label = models.CharField(max_length=150)
    actor_kind = models.CharField(max_length=20, choices=ActorKind.choices)
    # The tenant. No index of its own: (lab, -occurred_at) below serves the timeline and the FK.
    lab = models.ForeignKey(
        "labs.Lab",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        db_index=False,
    )
    # The strain whose timeline shows this event (ADR 0008, D13): its public id, no FK.
    # No index of its own: the partial (lab, strain_id, -occurred_at) index below serves it.
    strain_id = models.UUIDField(null=True, blank=True)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    request_id = models.CharField(max_length=64)
    batch_id = models.UUIDField(null=True, blank=True)
    reason = models.TextField(blank=True)
    subject_type = models.CharField(max_length=40)
    subject_id = models.UUIDField()  # public id: the subject may be gone later
    # {field: [old, new]}, ids only, never secrets; a personal field is "changed", no value
    changes = models.JSONField(default=dict)
    schema_version = models.PositiveSmallIntegerField(default=1)

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        constraints = (
            models.CheckConstraint(
                condition=~Q(actor_kind=ActorKind.USER) | Q(actor__isnull=False),
                name="audit_auditevent_user_needs_actor",
            ),
            models.CheckConstraint(
                condition=~Q(event_type__in=reason_required_codes()) | Q(reason__regex=r"\S"),
                name="audit_auditevent_reason_required",
            ),
            models.CheckConstraint(
                condition=Q(actor_kind__in=ActorKind.values),
                name="audit_auditevent_actor_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(channel__in=Channel.values),
                name="audit_auditevent_channel_valid",
            ),
        )
        indexes = (
            models.Index(
                fields=["subject_type", "subject_id", "occurred_at"],
                name="audit_event_subject_idx",
            ),
            models.Index(fields=["request_id"], name="audit_event_request_idx"),
            models.Index(fields=["txid"], name="audit_event_txid_idx"),
            models.Index(fields=["actor", "-occurred_at"], name="audit_event_actor_time_idx"),
            models.Index(fields=["lab", "-occurred_at"], name="audit_event_lab_time_idx"),
            # Most events (users, labs, logins) name no strain: they stay out of this index.
            models.Index(
                fields=["lab", "strain_id", "-occurred_at"],
                name="audit_event_strain_time_idx",
                condition=Q(strain_id__isnull=False),
            ),
            BrinIndex(fields=["occurred_at"], name="audit_event_time_brin"),
        )

    def __str__(self) -> str:
        return f"{self.event_type} by {self.actor_label}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnly("audit rows are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AppendOnly("audit rows are append-only")


class RowChange(models.Model):
    """One row written by the row audit triggers (migration 0003), never by Python.

    It catches what services cannot: QuerySet.update(), bulk_create, raw SQL,
    COPY and psql sessions. actor_id and request_id come from
    audited_atomic()'s set_config, so a row with a null actor_id was changed
    outside the application, and a txid with row changes but no AuditEvent is
    a change that no service explains. actor_id is the user's internal id
    without a foreign key: the trigger cannot trust a session setting to name
    an existing user. It is a claim, not proof: any session can set
    app.actor_id. The trigger keeps it only when it is a bigint, otherwise it
    stores null and sets actor_claim_invalid (migration 0008), so a malformed
    value never blocks a write. request_id is cut to 64 characters.

    table_label is the stable name from the trigger arguments ("users.user"),
    not the table name or oid, which change on a rename or a restore. row_pk is
    the primary key as text, a JSON array for a composite key, null only for
    TRUNCATE.
    """

    occurred_at = models.DateTimeField(db_default=TransactionNow())
    stmt_at = models.DateTimeField()  # statement_timestamp(): groups one client statement
    txid = models.BigIntegerField()
    table_label = models.CharField(max_length=100)
    row_pk = models.TextField(null=True)  # noqa: DJ001 (null means a whole-table TRUNCATE)
    op = models.CharField(max_length=8, choices=Op.choices)
    old = models.JSONField(null=True)  # UPDATE: only the changed columns. INSERT: null
    new = models.JSONField(null=True)  # UPDATE: only the changed columns. DELETE: null
    actor_id = models.BigIntegerField(null=True)
    actor_claim_invalid = models.BooleanField(db_default=False)  # app.actor_id was not a bigint
    # null, not "": the trigger found no request id (a change from outside the app).
    request_id = models.CharField(max_length=64, null=True)  # noqa: DJ001
    db_role = models.CharField(max_length=63)  # session_user: the login, also from psql
    db_application = models.CharField(max_length=64)  # application_name, set by the client

    objects = AppendOnlyQuerySet["RowChange"].as_manager()

    class Meta:
        constraints = (
            models.CheckConstraint(condition=Q(op__in=Op.values), name="audit_rowchange_op_valid"),
            models.CheckConstraint(
                condition=Q(op=Op.TRUNCATE, row_pk__isnull=True)
                | (~Q(op=Op.TRUNCATE) & Q(row_pk__isnull=False)),
                name="audit_rowchange_pk_unless_truncate",
            ),
        )
        indexes = (
            models.Index(
                fields=["table_label", "row_pk", "-occurred_at"], name="audit_row_subject_idx"
            ),
            models.Index(fields=["request_id"], name="audit_row_request_idx"),
            models.Index(fields=["txid"], name="audit_row_txid_idx"),
            models.Index(fields=["actor_id", "-occurred_at"], name="audit_row_actor_time_idx"),
            BrinIndex(fields=["occurred_at"], name="audit_row_time_brin"),
        )

    def __str__(self) -> str:
        return f"{self.op} {self.table_label} {self.row_pk}"

    def save(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AppendOnly("row changes are written by the database trigger only")

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AppendOnly("audit rows are append-only")

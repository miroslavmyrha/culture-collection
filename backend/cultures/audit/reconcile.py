"""Row changes that no service event explains: the alarm of ADR 0005.

Every audited write leaves AuditEvent rows and RowChange rows with the same
txid. A RowChange is reported when:
- no_event: no AuditEvent has its txid. Something wrote a regulated table
  outside the services: psql, a script, a forgotten QuerySet.update(), a data
  migration that recorded no event;
- invalid_actor: app.actor_id held something that is not a user id;
- no_actor: its actor is null although the transaction's events all name a
  user, so the actor never reached the trigger.
A null actor next to an event of a system actor (a command, a task, a data
migration in migration_audit()) is a known source: listed with that event's
channel and label, not an alarm.

Both queries filter on occurred_at (BRIN) and look events up by txid (a btree
on both tables). The first is NOT EXISTS, which PostgreSQL plans as an anti
join. NOT IN cannot be, and took 811 ms on 300 000 events in the review.
"""

from dataclasses import dataclass
from datetime import datetime

from django.db import connection

NO_EVENT = "no_event"
INVALID_ACTOR = "invalid_actor"
NO_ACTOR = "no_actor"
KNOWN = "known"
ALARMS = (NO_EVENT, INVALID_ACTOR, NO_ACTOR)

WITHOUT_EVENT = """
SELECT r.txid, r.table_label, r.db_role, r.db_application, count(*), min(r.occurred_at),
       '', ''
  FROM audit_rowchange r
 WHERE r.occurred_at >= %s
   AND NOT EXISTS (SELECT FROM audit_auditevent e WHERE e.txid = r.txid)
 GROUP BY r.txid, r.table_label, r.db_role, r.db_application
"""

# Null or invalid actors in transactions that have events. kind: invalid_actor,
# known (a system actor's event explains the null), or no_actor.
WITHOUT_ACTOR = """
SELECT r.txid, r.table_label, r.db_role, r.db_application, count(*), min(r.occurred_at),
       e.channels, e.labels,
       CASE WHEN bool_or(r.actor_claim_invalid) THEN 'invalid_actor'
            WHEN e.system THEN 'known'
            ELSE 'no_actor' END
  FROM audit_rowchange r
  JOIN LATERAL (
        SELECT bool_or(ev.actor_kind <> 'user') AS system,
               string_agg(DISTINCT ev.channel, ',') AS channels,
               string_agg(DISTINCT ev.actor_label, ',') AS labels
          FROM audit_auditevent ev
         WHERE ev.txid = r.txid
       ) e ON e.system IS NOT NULL
 WHERE r.occurred_at >= %s
   AND (r.actor_id IS NULL OR r.actor_claim_invalid)
 GROUP BY r.txid, r.table_label, r.db_role, r.db_application, e.system, e.channels, e.labels
"""


@dataclass(frozen=True)
class Finding:
    kind: str
    txid: int
    table_label: str
    db_role: str
    db_application: str
    rows: int
    first_at: datetime
    channels: str
    labels: str

    @property
    def alarm(self) -> bool:
        return self.kind in ALARMS


def reconcile(since: datetime) -> list[Finding]:
    """Findings for row changes since `since`, oldest first."""
    with connection.cursor() as cursor:
        cursor.execute(WITHOUT_EVENT, [since])
        findings = [Finding(NO_EVENT, *row) for row in cursor.fetchall()]
        cursor.execute(WITHOUT_ACTOR, [since])
        findings += [Finding(row[-1], *row[:-1]) for row in cursor.fetchall()]
    return sorted(findings, key=lambda f: (f.first_at, f.txid, f.kind, f.table_label))

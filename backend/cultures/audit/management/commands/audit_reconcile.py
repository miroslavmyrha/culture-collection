"""Report row changes that no service event explains (cultures/audit/reconcile.py).

    python manage.py audit_reconcile --since 25h     # the default, also 7d or an ISO date or time

Prints one line per finding and exits 1 when any is an alarm (no_event,
invalid_actor, no_actor), so a scheduler can alert on the exit code. Known
sources (a system actor's event in the same transaction, such as a data
migration in migration_audit()) are printed as "known" and do not fail the run.
Read-only: the runtime role may run it.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from cultures.audit.reconcile import reconcile

_RELATIVE = re.compile(r"^(\d{1,5})([hd])$")


def parse_since(value: str, now: datetime) -> datetime:
    """`25h`, `7d`, an ISO date (midnight UTC) or an ISO date and time."""
    relative = _RELATIVE.fullmatch(value)
    if relative:
        amount, unit = int(relative[1]), relative[2]
        return now - (timedelta(hours=amount) if unit == "h" else timedelta(days=amount))
    moment = parse_datetime(value)
    if moment is None:
        day = parse_date(value)
        if day is None:
            raise CommandError(f"--since {value!r}: use 25h, 7d, 2026-10-17 or 2026-10-17T06:00Z")
        moment = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return moment if timezone.is_aware(moment) else moment.replace(tzinfo=UTC)


class Command(BaseCommand):
    help = "Report audit row changes with no service event or no actor, exit 1 on an alarm."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--since", default="25h", help="25h (default), 7d or an ISO date/time")

    def handle(self, *args: Any, **options: Any) -> None:
        since = parse_since(options["since"], timezone.now())
        findings = reconcile(since)
        for finding in findings:
            self.stdout.write(
                f"{finding.kind} txid={finding.txid} table={finding.table_label}"
                f" rows={finding.rows} first={finding.first_at.isoformat()}"
                f" db_role={finding.db_role} application={finding.db_application!r}"
                + (
                    f" channel={finding.channels} label={finding.labels!r}"
                    if finding.channels
                    else ""
                )
            )
        alarms = sum(1 for finding in findings if finding.alarm)
        summary = f"since {since.isoformat()}: {alarms} alarms, {len(findings) - alarms} known"
        if alarms:
            raise CommandError(summary, returncode=1)
        self.stdout.write(summary)

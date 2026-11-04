"""Verify the audit hash chains and their anchors, and exit 1 on the first break.

    python manage.py audit_chain_verify              # both chains
    python manage.py audit_chain_verify --chain event

Reads only: SELECT on audit_auditevent, audit_rowchange and audit_chainanchor is
all it needs, so it runs as the migration role, which can read everything, or as
the runtime role. Run it from a job of its own, not from the API process: the
point of ADR 0009 is evidence an edit of the history cannot hide from.

It prints one line per chain, then the first break of that chain if there is one,
then one line per anchor finding, then what this build can say about each
authority's token. It exits 1 when any chain is broken or any anchor no longer
matches, so the schedule alerts on the exit code (like audit_reconcile).

A chain with no anchor for a long time is a gap in the anchors, not a break
(ADR 0009, Consequences), so it is printed and does not fail the run. The daily
job (manage.py audit_chain_anchor) is what alerts on that.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from cultures.audit.chain import CHAINS, Report, verify
from cultures.audit.timestamping import token_note


class Command(BaseCommand):
    help = "Verify the audit hash chains and their anchors, exit 1 on a break."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--chain", choices=sorted(CHAINS), help="only this chain")
        parser.add_argument("--batch", type=int, default=5000, help="rows read at a time")

    def _report(self, report: Report) -> None:
        walked = report.walked
        head = "no rows" if walked.head_id is None else f"head {walked.head_id}"
        state = "intact" if report.intact else "BROKEN"
        self.stdout.write(
            f"{report.chain}: {walked.rows} rows, {head}, {len(report.anchors)} anchors: {state}"
        )
        if walked.first_break is not None:
            found = walked.first_break
            self.stdout.write(f"{report.chain}: first break {found.kind} at row {found.row_id}:")
            self.stdout.write(f"  {found.detail}")
        for finding in report.findings:
            self.stdout.write(
                f"{report.chain}: anchor {finding.anchor_id} over row {finding.head_id}:"
                f" {finding.kind}: {finding.detail}"
            )
        if report.anchors:
            last = report.anchors[-1]
            self.stdout.write(
                f"{report.chain}: last anchored {last.anchored_at.isoformat()} by"
                f" {last.authority} over row {last.head_id}"
            )
            for stamped_by in sorted({one.authority for one in report.anchors}):
                self.stdout.write(
                    f"{report.chain}: token of {stamped_by}: {token_note(stamped_by)}"
                )
        elif walked.rows:
            self.stdout.write(f"{report.chain}: never anchored, so nothing outside vouches for it")

    def handle(self, *args: Any, **options: Any) -> None:
        chosen = [CHAINS[options["chain"]]] if options["chain"] else list(CHAINS.values())
        reports = [verify(chain, batch=options["batch"]) for chain in chosen]
        for report in reports:
            self._report(report)
        broken = [report.chain for report in reports if not report.intact]
        if broken:
            raise CommandError(f"broken: {', '.join(broken)}", returncode=1)
        self.stdout.write(f"intact: {', '.join(report.chain for report in reports)}")

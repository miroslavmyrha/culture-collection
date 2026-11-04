"""Stamp each audit chain's head with a qualified timestamp, once a day.

    python manage.py audit_chain_anchor              # both chains
    python manage.py audit_chain_anchor --chain event

ADR 0009 asks for a qualified electronic timestamp over the head of the chain
once a day. This is that job. It is not on any write path: a failing or missing
authority leaves the head unanchored and ends the run with exit code 1 for the
schedule to alert on, and no write ever waits for it (ADR 0009, Consequences: "A
missed day leaves a gap in the anchors, not in the chain").

Anchoring a head that an anchor already covers writes nothing, so running the
job twice is a no-op.

The authority is configured in AUDIT_TIMESTAMP_AUTHORITY and is a paid external
service; the default stamps nothing (cultures/audit/timestamping.py).
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from cultures.audit.anchors import anchor
from cultures.audit.chain import CHAINS
from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, Channel

LABEL = "command:audit_chain_anchor"


class Command(BaseCommand):
    help = "Stamp each audit chain's head with a qualified timestamp, exit 1 when it fails."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--chain", choices=sorted(CHAINS), help="only this chain")

    def handle(self, *args: Any, **options: Any) -> None:
        chosen = [CHAINS[options["chain"]]] if options["chain"] else list(CHAINS.values())
        with audit_context(channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label=LABEL):
            outcomes = [anchor(chain) for chain in chosen]
        for outcome in outcomes:
            self.stdout.write(f"{outcome.chain}: {outcome.kind}: {outcome.detail}")
        alarms = [outcome.chain for outcome in outcomes if outcome.alarm]
        if alarms:
            raise CommandError(f"unanchored: {', '.join(alarms)}", returncode=1)

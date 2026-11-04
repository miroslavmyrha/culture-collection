"""Anchoring a chain's head: the daily job of ADR 0009 (#175).

One run per chain: read the head, ask the timestamp authority to stamp its hash,
store the answer as a `ChainAnchor`. The anchor names the row it covers, so later
rows are covered by the next anchor and a day on which the authority could not be
reached "leaves a gap in the anchors, not in the chain" (ADR 0009, Consequences).

The row is written by `audit_chain_anchor_record`, a SECURITY DEFINER function
owned by the audit owner: the runtime role has only SELECT on the table, and the
function refuses an anchor that does not name a real row holding the hash it
claims, so no caller can stamp a head that never existed.

The anchor row is itself the record that the job ran: it is an append-only audit
row with the day, the authority and the token. No service event is recorded for
it, so anchoring a head that is already anchored writes nothing and a second run
on a quiet day is a no-op.

Nothing here is on a write path. The authority is an external service, and a
failure only ends the job with a non-zero exit code for the schedule to alert on
(`manage.py audit_chain_anchor`).
"""

import uuid
from dataclasses import dataclass

from django.db import connection

from .chain import Chain, head
from .context import audited_atomic
from .models import ChainAnchor
from .timestamping import Token, Unavailable, authority

ANCHORED = "anchored"
EMPTY = "empty"  # the chain has no rows yet: nothing to stamp
COVERED = "covered"  # an anchor already covers this head
UNANCHORED = "unanchored"  # the authority could not be reached: the alarm

RECORD = "SELECT audit_chain_anchor_record(%s, %s, %s, %s, %s, %s, %s)"


@dataclass(frozen=True)
class Outcome:
    chain: str
    kind: str
    detail: str
    head_id: int | None = None
    stamped_by: str = ""

    @property
    def alarm(self) -> bool:
        return self.kind == UNANCHORED


def _covered(chain: Chain, head_id: int) -> bool:
    return ChainAnchor.objects.filter(chain=chain.name, head_id=head_id).exists()


def _write(chain: Chain, head_id: int, head_hash: bytes, token: Token) -> uuid.UUID:
    public_id = uuid.uuid4()
    with audited_atomic(), connection.cursor() as cursor:
        cursor.execute(
            RECORD,
            [
                chain.name,
                head_id,
                head_hash,
                token.authority,
                token.token,
                token.time,
                str(public_id),
            ],
        )
    return public_id


def anchor(chain: Chain) -> Outcome:
    """Stamp this chain's head. A failing authority is reported, never raised."""
    found = head(chain)
    if found is None:
        return Outcome(chain.name, EMPTY, "the chain has no rows yet")
    head_id, head_hash = found
    if _covered(chain, head_id):
        return Outcome(chain.name, COVERED, "an anchor already covers this head", head_id)
    try:
        token = authority().stamp(head_hash)
    except Unavailable as problem:
        return Outcome(chain.name, UNANCHORED, str(problem), head_id)
    _write(chain, head_id, head_hash, token)
    return Outcome(
        chain.name,
        ANCHORED,
        f"head {head_id} stamped by {token.authority}",
        head_id,
        token.authority,
    )

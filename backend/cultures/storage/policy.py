"""May a unit take material of a risk group (ADR 0009, the may_store gate)?

Written with the tree (#14), called by every placement from #16 on. A vial goes
into a box, never into a rack or a freezer directly. The box and every unit
above it must be active: a freezer out of service takes nothing, also not
through a rack in it. The cap is the lowest `max_risk_group` along the path:
each root states one, a unit below may lower it, never raise it. The facts come
from the database in one query (StorageUnit.objects.with_path_facts()), so
the gate reads the committed tree, not a copy the caller holds.
"""

from dataclasses import dataclass

from .models import StorageUnit, UnitKind


@dataclass(frozen=True)
class StoreDecision:
    allowed: bool
    code: str = ""  # why not: not_a_box, unit_not_active, risk_group_above_cap
    detail: str = ""
    cap: int | None = None  # the effective cap of the unit


ALLOWED = StoreDecision(allowed=True)


def decide(*, kind: str, path_active: bool, cap: int | None, risk_group: int) -> StoreDecision:
    """The rule on the facts alone, no query. A cap that is missing refuses everything: every
    root has one (a check constraint), so only a broken row gets here."""
    if kind != UnitKind.BOX:
        return StoreDecision(False, "not_a_box", "Material is stored in boxes only.", cap)
    if not path_active:
        return StoreDecision(
            False,
            "unit_not_active",
            "The box or a unit holding it is out of service or retired.",
            cap,
        )
    if cap is None or risk_group > cap:
        return StoreDecision(
            False,
            "risk_group_above_cap",
            f"This box takes risk group {cap} at most." if cap else "This box has no cap.",
            cap,
        )
    return StoreDecision(True, cap=cap)


def may_store(*, unit: StorageUnit, risk_group: int) -> StoreDecision:
    """The decision for the unit as committed now. Callers that place material hold the lab
    lock, so no unit on the path changes between this read and their commit."""
    fresh = StorageUnit.objects.filter(pk=unit.pk).with_path_facts().get()
    facts = vars(fresh)  # the annotations, which the model's type does not know
    return decide(
        kind=fresh.kind,
        path_active=facts["path_active"],
        cap=facts["effective_max_risk_group"],
        risk_group=risk_group,
    )

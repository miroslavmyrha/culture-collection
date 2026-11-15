"""The lab lock: every rule that holds for a whole lab is checked under it.

`SELECT ... FOR UPDATE` on the lab row, inside the caller's transaction. Member
changes take it before they read the managers (labs.services), the strain
accession takes it before it reads the counter and the lab's authorisations,
and changes to authorisations take it too, so a permit ended at the same
moment as an accession is seen by one of them in full. Lock order everywhere:
user rows, then lab rows by pk, then the rows of that lab.
"""

from django.db import connection

from cultures.core.exceptions import Forbidden

from .access import Access
from .models import Lab, Membership
from .permissions import Perm, Role, role_has


def lock_lab(lab_id: int) -> Lab:
    """The committed lab row, locked until the caller's transaction ends."""
    lab = Lab.objects.select_for_update().get(pk=lab_id)
    _held().add(lab_id)
    return lab


def _held() -> set[int]:
    """The labs locked through lock_lab in the transaction that runs now. Kept on the outermost
    atomic block, so the next transaction starts with none (no service enters one twice)."""
    if not connection.in_atomic_block:
        return set()
    outer: object = connection.atomic_blocks[0]
    held: set[int] | None = getattr(outer, "cultures_locked_labs", None)
    if held is None:
        held = set()
        setattr(outer, "cultures_locked_labs", held)  # noqa: B010 (an attribute of Django's object)
    return held


def require_committed(access: Access, lab_id: int, perm: Perm) -> Role:
    """The actor's role as committed now, read under the lab lock the caller took with lock_lab,
    not the role the request began with (#232): a member demoted meanwhile is refused. Called
    without that lock it is a programming error and fails loudly."""
    if lab_id not in _held():
        raise RuntimeError(f"require_committed for lab {lab_id} without its lock: lock_lab first")
    role = (
        Membership.objects.filter(lab_id=lab_id, user=access.user, user__is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    if role is None or not role_has(Role(role), perm):
        raise Forbidden
    return Role(role)

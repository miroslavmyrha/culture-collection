"""The lab lock: every rule that holds for a whole lab is checked under it.

`SELECT ... FOR UPDATE` on the lab row, inside the caller's transaction. Member
changes take it before they read the managers (labs.services), the strain
accession takes it before it reads the counter and the lab's authorisations,
and changes to authorisations take it too, so a permit ended at the same
moment as an accession is seen by one of them in full. Lock order everywhere:
user rows, then lab rows by pk, then the rows of that lab.
"""

from .models import Lab


def lock_lab(lab_id: int) -> Lab:
    """The committed lab row, locked until the caller's transaction ends."""
    return Lab.objects.select_for_update().get(pk=lab_id)

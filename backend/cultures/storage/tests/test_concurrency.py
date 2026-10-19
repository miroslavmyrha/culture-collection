"""The tree lock: a box added under a rack while the rack moves gets the rack's new path.

Real threads and real transactions, raw SQL on both sides, so no service and no lab row lock
is involved: only the path trigger's advisory lock per lab. The mover changes the rack's
parent and holds its transaction open for a moment; the adder inserts a box under the rack
meanwhile. With the lock the insert waits until the move has committed and then reads the
new path. Without it the insert reads the rack's old path, the move's cascade cannot see the
uncommitted box, and the box keeps a path through the freezer it has left: the assertion
fails every time, not only when the timing is unlucky.
"""

import threading
import time

import pytest
from django.db import connection, transaction

from cultures.storage.models import BoxType, StorageUnit, UnitKind

from .conftest import MakeUnit, Tree

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow]
HOLD = 1.0  # seconds the mover keeps its transaction open after the move


def test_a_box_added_while_its_rack_moves_gets_the_new_path(
    tree: Tree, make_unit: MakeUnit, box_9x9: BoxType
) -> None:
    tank = make_unit(UnitKind.LN2_TANK, "Tank B")
    moved = threading.Event()
    outcomes: dict[str, str] = {}

    def mover() -> None:
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE storage_storageunit SET parent_id = %s WHERE id = %s",
                    [tank.pk, tree.rack.pk],
                )
                moved.set()
                time.sleep(HOLD)
            outcomes["mover"] = "done"
        finally:
            moved.set()
            connection.close()

    def adder() -> None:
        moved.wait(timeout=5)
        try:
            with transaction.atomic():
                StorageUnit.objects.create(
                    lab=tree.rack.lab,
                    kind=UnitKind.BOX,
                    name="Box added meanwhile",
                    parent=tree.rack,
                    box_type=box_9x9,
                    rows=9,
                    cols=9,
                )
            outcomes["adder"] = "done"
        finally:
            connection.close()

    threads = [threading.Thread(target=mover), threading.Thread(target=adder)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert outcomes == {"mover": "done", "adder": "done"}
    added = StorageUnit.objects.get(name="Box added meanwhile")
    assert list(added.path) == [tank.pk, tree.rack.pk, added.pk]

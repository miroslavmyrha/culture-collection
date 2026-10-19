"""Data and helpers for the lineage tests. Fixtures: fixtures.py, imported by conftest.py.

The lab, people and taxa are the strains tests' (Mycology, MYC, one member of every role;
the invented taxa Testella and Mockia), the storage tree the storage tests' (Freezer A, risk
group 2 at most > Rack 1 > Box 1, 9 x 9).
"""

from collections.abc import Callable
from datetime import date
from typing import Any

from cultures.audit.models import AuditEvent, RowChange
from cultures.labs.access import access_for
from cultures.lineage import services
from cultures.lineage.models import Batch, Method, Passage, Purpose, Vial, VialPlacement
from cultures.storage.models import StorageUnit
from cultures.strains.tests.conftest import LAB_ID
from cultures.users.models import User

LAB_URL = f"/api/v1/labs/{LAB_ID}"
PASSAGES_URL = f"{LAB_URL}/passages/"
BATCHES_URL = f"{LAB_URL}/batches/"
VIALS_URL = f"{LAB_URL}/vials/"
GRANTS_URL = f"{LAB_URL}/location-grants/"


def new_batch(**changes: Any) -> services.NewBatch:
    values: dict[str, Any] = {
        "method": Method.CRYO_MINUS80,
        "purpose": Purpose.DISTRIBUTION,
        "preserved_on": date(2026, 10, 1),
        "vial_count": 3,
        "cryoprotectant": "10 % glycerol",
        **changes,
    }
    return services.NewBatch(**values)


def preserve(actor: User, passage: Passage, **changes: Any) -> Batch:
    """Through the service, in the caller's audit context."""
    return services.batch_preserve(
        access=access_for(actor), passage=passage, data=new_batch(**changes)
    )


def vials_of(batch: Batch) -> list[Vial]:
    return list(Vial.objects.filter(batch=batch).order_by("seq"))


def open_place(vial: Vial) -> tuple[StorageUnit, int, int] | None:
    placement = VialPlacement.objects.filter(vial=vial, removed_at__isnull=True).first()
    return None if placement is None else (placement.box, placement.row, placement.col)


def snapshot() -> tuple[Any, ...]:
    """Every lineage table, every event and every row change."""
    tables = (Passage, Batch, Vial, VialPlacement)
    rows = tuple(list(m._default_manager.order_by("pk").values()) for m in tables)
    return (*rows, AuditEvent.objects.count(), RowChange.objects.count())


MakeBatch = Callable[..., Batch]

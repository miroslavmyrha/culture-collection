"""seed_scale: many strains through the services, on top of seed_dev, development only (#71)."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from cultures.audit.models import AuditEvent
from cultures.audit.reconcile import reconcile
from cultures.lineage.models import Batch, Vial, VialPlacement
from cultures.storage.models import StorageUnit, UnitKind
from cultures.strains.models import Strain

from .test_seed_dev import EPOCH, env, seed  # noqa: F401 (env is a fixture)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("env")]


def scale(*args: str) -> str:
    out = StringIO()
    with override_settings(DEBUG=True, DEV_DATA_ALLOWED=True):
        call_command("seed_scale", *args, stdout=out)
    return out.getvalue()


def scaled() -> list[Strain]:
    return list(Strain.objects.filter(name_as_received__contains=" SCALE ").order_by("pk"))


def test_it_refuses_without_debug() -> None:
    with override_settings(DEBUG=False, DEV_DATA_ALLOWED=True), pytest.raises(CommandError):
        call_command("seed_scale", stdout=StringIO())


def test_it_needs_seed_dev_first() -> None:
    with pytest.raises(CommandError, match="seed_dev"):
        scale("--strains", "1")


def test_it_adds_strains_with_placed_vials_and_a_regulated_share() -> None:
    seed()
    out = scale("--strains", "12", "--vials", "40", "--regulated-every", "4")
    strains = scaled()
    assert len(strains) == 12
    assert sum(s.name_as_received.startswith("Clostridium perfringens") for s in strains) == 3
    vials = Vial.objects.filter(batch__strain__in=strains)
    assert vials.count() == 12 * 40
    placed = VialPlacement.objects.filter(vial__in=vials, removed_at__isnull=True)
    assert placed.count() == 12 * 40
    boxes = StorageUnit.objects.filter(kind=UnitKind.BOX, name__startswith="Scale box")
    assert boxes.count() == 6  # 2 strains of 40 vials per 100-place box
    assert "12 strains, 480 vials in 6 boxes" in out


def test_its_writes_are_audited_and_a_second_run_adds_nothing() -> None:
    seed()
    scale("--strains", "3", "--vials", "2")
    assert [f for f in reconcile(EPOCH) if f.alarm] == []
    events, batches = AuditEvent.objects.count(), Batch.objects.count()
    scale("--strains", "3", "--vials", "2")
    assert (len(scaled()), Batch.objects.count()) == (3, batches)
    assert AuditEvent.objects.count() == events


@pytest.mark.parametrize(
    "args", [["--strains", "0"], ["--vials", "101"], ["--regulated-every", "0"]]
)
def test_it_refuses_sizes_out_of_range(args: list[str]) -> None:
    with pytest.raises(CommandError, match="at least one strain"):
        scale(*args)

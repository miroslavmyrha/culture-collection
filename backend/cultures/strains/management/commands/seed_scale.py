"""Add a collection at scale to a development database (#71), on top of seed_dev.

    DEV_PASSWORD=... python manage.py seed_dev
    python manage.py seed_scale --strains 5000 --vials 10

In lab BAC: a storage tree of 10 x 10 boxes, and `--strains` deposits received, checked and
accepted through the deposit services (passage 0 from each deposit), one in `--regulated-every`
of them a regulated strain, each with one batch of `--vials` vials placed in the boxes. Every
write goes through the services, so the audit trail explains every row (audit_reconcile). A
second run adds only what is missing. Development settings only, as seed_dev.
Ends with ANALYZE.
"""

import time
from dataclasses import dataclass
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection

from cultures.audit.context import audit_context, audited_atomic
from cultures.audit.models import ActorKind, Channel
from cultures.deposits import seeding as seed_deposits
from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.lineage import seeding as seed_lineage
from cultures.lineage.models import Batch
from cultures.storage import seeding as seed_storage

from .seed_dev import batch, deposit, load, refusal, staff, unit

LAB = "BAC"
PLAIN = "Bacillus subtilis 168 DEP-1"
REGULATED = "Clostridium perfringens DEP-8"
BOX_TYPE = ("100-place cryobox (10 x 10)", 10, 10)
BOXES_PER_RACK = 20
LABEL = "command:seed_scale"
REASON = "development data at scale (#71)"


def box_path(index: int) -> list[str]:
    """Where box number `index` stands: freezer, rack, box."""
    rack = index // BOXES_PER_RACK
    return [f"Scale freezer {rack // 10 + 1}", f"Scale rack {rack + 1}", f"Scale box {index + 1}"]


def storage(boxes: int) -> list[dict[str, Any]]:
    """The scale storage tree as seed_dev.json writes one: freezers of 10 racks of 20 boxes."""
    freezers: dict[str, dict[str, Any]] = {}
    for index in range(boxes):
        freezer, rack, box = box_path(index)
        f = freezers.setdefault(
            freezer,
            {
                "kind": "freezer",
                "name": freezer,
                "temperature_c": -80,
                "max_risk_group": 2,
                "children": [],
            },
        )
        if not f["children"] or f["children"][-1]["name"] != rack:
            f["children"].append(
                {"kind": "rack", "name": rack, "slot": len(f["children"]) + 1, "children": []}
            )
        r = f["children"][-1]
        r["children"].append(
            {"kind": "box", "name": box, "slot": len(r["children"]) + 1, "box_type": BOX_TYPE[0]}
        )
    return list(freezers.values())


def sizes(options: dict[str, Any]) -> tuple[int, int, int]:
    """Strains, vials per strain and the share of regulated strains, checked."""
    strains, vials, every = options["strains"], options["vials"], options["regulated_every"]
    if strains < 1 or not 1 <= vials <= BOX_TYPE[1] * BOX_TYPE[2] or every < 1:
        raise CommandError(
            "Give at least one strain, 1 to 100 vials and --regulated-every of 1 or more."
        )
    return strains, vials, every


@dataclass(frozen=True)
class Run:
    """What every strain of a run shares."""

    curator: Access
    bench: Access
    lab: Lab
    taxa: Any
    vials: int


def one_strain(run: Run, template: dict[str, Any], i: int, box: list[str]) -> None:
    """Deposit number i, accepted, and its batch of vials in the box, unless it is there."""
    name = f"{template['name_as_received']} SCALE {i:05d}"
    with audited_atomic():
        made, _ = seed_deposits.deposit(
            run.curator, run.lab, deposit({**template, "name_as_received": name}, run.taxa)
        )
        strain = made.strain
        if strain is None or Batch.objects.filter(strain=strain).exists():
            return
        row = {
            "method": "cryo_minus80",
            "purpose": "distribution",
            "preserved_on": template["received_on"],
            "vial_count": run.vials,
            "cryoprotectant": "10 % glycerol",
            "passage": 0,
            "box": box,
        }
        seed_lineage.batches(run.bench, strain, [batch(row)])


class Command(BaseCommand):
    help = "Add thousands of strains and tens of thousands of vials to a seed_dev database (#71)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--strains", type=int, default=5000)
        parser.add_argument("--vials", type=int, default=10, help="vials per strain, one batch")
        parser.add_argument("--regulated-every", type=int, default=10)

    def handle(self, *args: Any, **options: Any) -> None:
        reason = refusal()
        if reason:
            raise CommandError(reason)
        strains, vials, every = sizes(options)
        lab = Lab.objects.filter(code=LAB).first()
        if lab is None:
            raise CommandError("Run seed_dev first: seed_scale adds to its lab BAC.")
        data = load()
        templates = {row["name_as_received"]: row for row in data["deposits"] if row["lab"] == LAB}
        per_box = BOX_TYPE[1] * BOX_TYPE[2] // vials
        boxes = -(-strains // per_box)
        started = time.monotonic()
        with audit_context(
            channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label=LABEL, reason=REASON
        ):
            curator = staff(LAB, Role.CURATOR)
            run = Run(curator, staff(LAB, Role.TECHNICIAN), lab, data["taxa"], vials)
            with audited_atomic():
                seed_storage.box_type(*BOX_TYPE)
                seed_storage.tree(curator, lab, [unit(row) for row in storage(boxes)])
            for i in range(strains):
                template = templates[REGULATED if i % every == every - 1 else PLAIN]
                one_strain(run, template, i, box_path(i // per_box))
                if (i + 1) % 500 == 0:
                    self.stdout.write(f"{i + 1} strains, {time.monotonic() - started:.0f} s")
        # Fresh planner statistics, as autovacuum would give a collection that grew slowly: a
        # plan made for the empty tables took the home overview from 15 ms to 300 ms (#71).
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE")
        took = time.monotonic() - started
        self.stdout.write(
            f"seed_scale: {strains} strains, {strains * vials} vials in {boxes} boxes, {took:.0f} s"
        )

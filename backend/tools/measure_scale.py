"""Measure the main screens' API on a seeded database (#71): median time and query count.

    python manage.py seed_scale && python tools/measure_scale.py [--json out.json]
        [--flat-with small.json] [--budget-ms 1000]

Each request runs once to warm up, then five times; the median time and the query count of the
last run are printed as a Markdown table. `--flat-with` compares the query counts with a run on
fewer rows and fails when one grows with the data; `--budget-ms` fails a screen slower than the
budget. CI runs both (job `scale`). Development settings, as the seeds.
"""

import argparse
import json
import os
import statistics
import sys
import time

import django

# Run as a script from backend/: the project root, not tools/, is where config lives.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

from cultures.core.testing.clients import with_second_factor  # noqa: E402
from cultures.labs.models import Lab  # noqa: E402
from cultures.lineage.models import Vial  # noqa: E402
from cultures.storage.models import StorageUnit, UnitKind  # noqa: E402
from cultures.strains.models import Strain  # noqa: E402
from cultures.users.models import User  # noqa: E402

RUNS = 5
OK = 200


def measure(client: Client, url: str) -> tuple[float, int, int]:
    """Median milliseconds, queries and status of GET url."""
    client.get(url)
    times = []
    for _ in range(RUNS):
        with CaptureQueriesContext(connection) as captured:
            started = time.perf_counter()
            response = client.get(url)
            times.append((time.perf_counter() - started) * 1000)
    return statistics.median(times), len(captured.captured_queries), response.status_code


def main(code: str, username: str, host: str = "localhost") -> dict[str, dict[str, float]]:
    """The measured screens: name -> ms, queries, status. Prints the table."""
    lab = Lab.objects.get(code=code)
    client = Client(HTTP_HOST=host)
    client.force_login(User.objects.get(username=username))
    with_second_factor(client)
    strain = Strain.objects.filter(lab=lab).order_by("-pk").first()
    box = (
        StorageUnit.objects.filter(lab=lab, kind=UnitKind.BOX, placements__isnull=False)
        .order_by("-pk")
        .first()
    )
    assert strain is not None and box is not None  # noqa: S101 (run after seed_scale)
    base = f"/api/v1/labs/{lab.public_id}"
    s = strain.public_id
    screens = [
        ("strain list", f"{base}/strains/?limit=25"),
        ("strain list, search", f"{base}/strains/?limit=25&search=SCALE"),
        ("vial list", f"{base}/vials/?limit=50"),
        ("deposit list", f"{base}/deposits/?limit=25"),
        ("request list", f"{base}/requests/?limit=25"),
        ("search, many hits", "/api/v1/me/search/?q=Bacillus"),
        ("search, one strain", f"/api/v1/me/search/?q={strain.accession_number}"),
        ("storage tree", f"{base}/storage-units/"),
        ("box grid", f"{base}/boxes/{box.public_id}/"),
        ("strain detail", f"{base}/strains/{s}/"),
        ("material: passages", f"{base}/passages/?strain={s}&limit=200"),
        ("material: batches", f"{base}/batches/?strain={s}&limit=200"),
        ("material: vials", f"{base}/vials/?strain={s}&limit=50"),
        ("home overview", "/api/v1/me/overview/"),
    ]
    strains = Strain.objects.filter(lab=lab).count()
    vials = Vial.objects.filter(lab=lab).count()
    boxes = StorageUnit.objects.filter(lab=lab, kind=UnitKind.BOX).count()
    sys.stdout.write(f"Lab {code}: {strains} strains, {vials} vials, {boxes} boxes\n" + "\n")
    sys.stdout.write(
        "| screen | ms (median of 5) | queries | status |\n|---|---:|---:|---:|" + "\n"
    )
    results: dict[str, dict[str, float]] = {}
    for name, url in screens:
        ms, queries, status = measure(client, url)
        results[name] = {"ms": round(ms, 1), "queries": queries, "status": status}
        sys.stdout.write(f"| {name} | {ms:.0f} | {queries} | {status} |" + "\n")
    return results


def problems(
    results: dict[str, dict[str, float]],
    small: dict[str, dict[str, float]] | None,
    budget: float | None,
) -> list[str]:
    """What fails: a status other than 200, a query count that grew, a screen over budget."""
    found = [f"{n}: status {r['status']}" for n, r in results.items() if r["status"] != OK]
    if small is not None:
        found += [
            f"{n}: {r['queries']} queries, {small[n]['queries']} on fewer rows"
            for n, r in results.items()
            if n in small and r["queries"] != small[n]["queries"]
        ]
    if budget is not None:
        found += [
            f"{n}: {r['ms']} ms over {budget}" for n, r in results.items() if r["ms"] > budget
        ]
    return found


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab", default="BAC")
    parser.add_argument("--user", default="bac-manager")
    parser.add_argument("--json")
    parser.add_argument("--flat-with")
    parser.add_argument("--budget-ms", type=float)
    args = parser.parse_args()
    measured = main(args.lab, args.user)
    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as out:
            json.dump(measured, out, indent=2)
    small = None
    if args.flat_with:
        with open(args.flat_with, encoding="utf-8") as f:
            small = json.load(f)
    failed = problems(measured, small, args.budget_ms)
    for line in failed:
        sys.stdout.write(f"FAILED: {line}" + "\n")
    sys.exit(1 if failed else 0)

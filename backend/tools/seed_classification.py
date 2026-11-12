#!/usr/bin/env python3
"""What the seeds' entry codes come to, read out of the official list data files (#211).

The seeds (``seed_dev``, ``seed_e2e``) name entry codes and nothing else about a classification.
This tool shows what a set of codes yields, and finds the codes of a name, from the same code
the seeds use (``cultures.biosafety.entry_seed``). Run it from the ``backend`` directory, where
Django and the data files are::

    python tools/seed_classification.py show 1.155
    python tools/seed_classification.py show 1.56 "cz-474-2002:annex-2 I.II 3"
    python tools/seed_classification.py standard bacillus-subtilis-168
    python tools/seed_classification.py under-genus "Staphylococcus epidermidis"
    python tools/seed_classification.py find "Clostridium perfringens"
    python tools/seed_classification.py search "Brucella"

``show`` takes the codes of one strain and prints the taxon, the risk group and the entry it was
read in, the basis in words and the restrictions. ``find`` lists the entries a taxon name matches,
as the Classification view of the app reads them. ``search`` lists the entries whose name holds the
text. Each prints JSON, one object, so a script can read it.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _setup() -> None:
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    import django  # noqa: PLC0415 (Django is configured before the modules that need it)

    django.setup()


def run(argv: Sequence[str]) -> dict[str, Any]:
    """The answer of one command line, as plain data."""
    from cultures.biosafety import entry_seed  # noqa: PLC0415 (after setup)

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("show", "standard", "under-genus", "find", "search"):
        sub.add_parser(name).add_argument("what", nargs="+")
    args = parser.parse_args(argv)
    what: list[str] = args.what
    match args.command:
        case "show":
            return dataclasses.asdict(entry_seed.listed(what))
        case "standard":
            return dataclasses.asdict(entry_seed.standard(what[0]))
        case "under-genus":
            return dataclasses.asdict(entry_seed.species_under_genus(" ".join(what)))
        case "find":
            return {
                "entries": [
                    dataclasses.asdict(e) for e in entry_seed.entries_matching(" ".join(what))
                ]
            }
        case _:
            pattern = re.compile(" ".join(what), re.IGNORECASE)
            return {
                "entries": [
                    dataclasses.asdict(e)
                    for rows in entry_seed.read_entries().values()
                    for e in rows
                    if pattern.search(e.name)
                ]
            }


def main(argv: Sequence[str] | None = None) -> int:
    _setup()
    from cultures.biosafety.entry_seed import SeedEntryError  # noqa: PLC0415 (after setup)

    try:
        answer = run(sys.argv[1:] if argv is None else argv)
    except SeedEntryError as error:
        sys.stderr.write(f"seed_classification: {error}\n")
        return 1
    sys.stdout.write(json.dumps(answer, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

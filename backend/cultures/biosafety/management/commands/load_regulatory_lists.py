"""Load the official lists of regulated agents and risk groups from the data files (#169).

    python manage.py load_regulatory_lists [--data-dir ...]

The files under ``cultures/biosafety/data`` are written from the official sources by
``tools/fetch_regulatory_lists.py`` (#187). The command reads them, checks each against the
SHA-256 the manifest records, and loads the ones the database does not hold yet. A changed file
becomes a new list version, which is then the current one; a file that is already loaded leaves
the database alone, so running the command twice in a row changes nothing the second time.

Lists are not editable in the app: no screen and no API writes one, and the database refuses an
update of an entry and a delete of either row (biosafety 0005). Loading again is the only way a
list changes, and migration 0006 did it once for the files of this version.
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, Channel
from cultures.biosafety import lists

LABEL = "command:load_regulatory_lists"
REASON = "the official lists as the data files hold them"


class Command(BaseCommand):
    help = "Load the official lists of regulated agents and risk groups from the data files."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--data-dir",
            default=str(lists.DATA_DIR),
            help="Where the data files and their manifest are (the app's data/ by default).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        with audit_context(
            channel=Channel.COMMAND,
            actor_kind=ActorKind.SYSTEM,
            actor_label=LABEL,
            reason=REASON,
        ):
            try:
                loaded = lists.load(data_dir=Path(options["data_dir"]))
            except lists.ListDataError as error:
                raise CommandError(str(error)) from error
        for one in loaded:
            what = "loaded" if one.created else "held already"
            self.stdout.write(
                f"{one.code} {one.version}: {what}, {one.entries} entries, "
                f"{one.matched} with a name to match"
            )

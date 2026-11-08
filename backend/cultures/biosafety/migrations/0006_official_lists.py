"""Load the official lists from the data files this version ships (#169).

Every database gets the lists with the schema, so a rule that reads them holds from the first
deploy on and in every test. A later version of a list is loaded by
``manage.py load_regulatory_lists``, which does exactly what this migration does and is
idempotent too: a data file whose SHA-256 the database already holds is skipped.

No audit event: a reading's own row says where it came from, which version it is, when it was
loaded and the SHA-256 of both the fetched text and the data file, and nothing can change it
(migration 0005), so the deploy that brought the files needs no event of its own and no
database starts its trail with four. The command records one, because there a person chose to
load a newer list.

The loader is the application's own module, not a frozen copy: the two tables are written by
nothing else, and a change to them changes the loader with them.
"""

from typing import Any

from django.db import migrations

from cultures.biosafety import lists


def load(apps: Any, schema_editor: Any) -> None:
    lists.load(record=False)


class Migration(migrations.Migration):
    dependencies = [("biosafety", "0005_regulatory_list_guards")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop, elidable=False)]

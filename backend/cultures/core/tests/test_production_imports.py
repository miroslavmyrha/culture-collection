"""The runtime image has only the production dependencies (`uv sync --no-dev`).

The tests run with the dev group installed, so an import of a dev-only package in app code or
a migration passes here and fails in production: distribution 0006 imported the migration
linter, and `migrate` and `/readyz` could not load the migrations in the image. A fresh
interpreter loads production settings, every migration and every app module with the
packages of the dev group refused, as they are in the image.
"""

import os
import secrets
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

from django.conf import settings
from packaging.requirements import Requirement

BACKEND = Path(settings.BASE_DIR)
ENV = {
    "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
    "DJANGO_ALLOWED_HOSTS": "app.example.com",
    "DJANGO_ADMIN_PATH": "ops-x7k2/",
    "DATABASE_URL": "postgres://u:p@db:5432/app",
}


def _closure(names: list[str]) -> set[str]:
    """The installed distributions these requirements pull in, normalised names."""
    seen: set[str] = set()
    todo = list(names)
    while todo:
        name = metadata.distribution(todo.pop()).metadata["Name"].lower().replace("_", "-")
        if name in seen:
            continue
        seen.add(name)
        for line in metadata.requires(name) or []:
            req = Requirement(line)
            if req.marker is None or req.marker.evaluate({"extra": ""}):
                try:
                    metadata.distribution(req.name)
                except metadata.PackageNotFoundError:
                    continue  # not installed here, so not importable either
                todo.append(req.name)
    return seen


def dev_only_modules() -> set[str]:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    runtime = _closure([Requirement(r).name for r in project["project"]["dependencies"]])
    dev = _closure([Requirement(r).name for r in project["dependency-groups"]["dev"]])
    dev_only = dev - runtime
    return {
        module
        for module, dists in metadata.packages_distributions().items()
        if all(d.lower().replace("_", "-") in dev_only for d in dists)
    }


LOAD_EVERYTHING = """
import importlib, importlib.abc, pkgutil, sys

REFUSED = set(sys.argv[1].split(","))

class Refuse(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.partition(".")[0] in REFUSED:
            raise ModuleNotFoundError(f"No module named {name!r} (a dev-only package)")
        return None

sys.meta_path.insert(0, Refuse())

import django
django.setup()

from django.db.migrations.loader import MigrationLoader
MigrationLoader(None, ignore_no_migrations=True)

import config, cultures
SKIP = {"tests", "testing", "conftest"}
for package in (config, cultures):
    for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        if SKIP.isdisjoint(info.name.split(".")):
            importlib.import_module(info.name)
print("ok")
"""


def test_the_dev_group_is_refused_as_in_the_image() -> None:
    refused = dev_only_modules()
    # The check is only as good as the list: these are what an app module would reach for.
    assert {"pytest", "django_migration_linter", "model_bakery", "time_machine"} <= refused
    assert {"django", "rest_framework", "psycopg"}.isdisjoint(refused)


def test_production_settings_load_every_migration_and_module_without_the_dev_group() -> None:
    result = subprocess.run(  # noqa: S603 (fixed interpreter and arguments)
        [sys.executable, "-c", LOAD_EVERYTHING, ",".join(sorted(dev_only_modules()))],
        cwd=BACKEND,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONDONTWRITEBYTECODE": "1",
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            **ENV,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "ok"

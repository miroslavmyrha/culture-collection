"""The deposits tests' fixtures: a passage comes from an accepted deposit."""

from cultures.deposits.tests.fixtures import depositor, make_deposit, make_depositor  # noqa: F401
from cultures.strains.tests.conftest import (  # noqa: F401 (fixtures)
    _no_last_login_update,
    curator,
    exempli,
    lab,
    testella,
)
